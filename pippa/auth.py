from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable

from .limits import new_request_id, sign_in_email_key


class AuthenticationError(RuntimeError):
    """A safe, user-displayable authentication failure."""


@dataclass(frozen=True)
class LogoutResult:
    remote_revocation_failed: bool = False
    cookie_cleanup_failed: bool = False


def auth_callback_allowed(has_active_session: bool, token_hash: str, verification_type: str) -> bool:
    """Accept only fresh email callbacks when no identity is active in the tab."""
    return bool(token_hash) and verification_type == "email" and not has_active_session


REMEMBERED_SESSION_COOKIE = "pippa_remembered_session"
REMEMBERED_INTENT_COOKIE = "pippa_remember_intent"
REMEMBERED_SESSION_SECONDS = 14 * 24 * 60 * 60


def clear_remembered_session_cookies(cookies: Any) -> None:
    """Remove both remembered-auth cookies and persist the deletion."""
    cookies.pop(REMEMBERED_SESSION_COOKIE, None)
    cookies.pop(REMEMBERED_INTENT_COOKIE, None)
    cookies.save()


def logout_safely(
    authenticated: Any,
    cookies: Any,
    clear_server_state: Callable[[], None],
) -> LogoutResult:
    """Always clear server identity, even when revocation or cookie I/O fails."""
    remote_failed = False
    cookie_failed = False
    try:
        if authenticated is not None:
            authenticated.sign_out()
    except Exception:
        remote_failed = True
    try:
        if cookies is not None:
            clear_remembered_session_cookies(cookies)
    except Exception:
        cookie_failed = True
    finally:
        clear_server_state()
    return LogoutResult(remote_failed, cookie_failed)


def parse_remembered_session_payload(raw_payload: str, now: int | None = None) -> tuple[str, str, int]:
    """Validate an encrypted cookie payload without trusting identity claims."""
    try:
        payload = json.loads(raw_payload)
        if not isinstance(payload, dict):
            raise ValueError("invalid payload")
        expires_at = int(payload.get("expires_at", 0))
        if expires_at <= (int(time.time()) if now is None else now):
            raise ValueError("expired")
        tokens = payload.get("tokens")
        if not isinstance(tokens, dict):
            raise ValueError("invalid tokens")
        access_token = str(tokens.get("access_token", "")).strip()
        refresh_token = str(tokens.get("refresh_token", "")).strip()
        if not access_token or not refresh_token:
            raise ValueError("missing tokens")
        return access_token, refresh_token, expires_at
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AuthenticationError("The saved browser sign-in is invalid or has expired.") from exc


def _safe_magic_link_error(exc: Exception) -> str:
    """Translate provider/runtime failures without exposing secrets or internals."""
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__

    combined = " ".join(
        f"{type(item).__name__} {item}" for item in chain
    ).lower()
    statuses = {
        getattr(item, "status", None) or getattr(item, "status_code", None)
        for item in chain
    }

    if "pippa_auth_resend" in combined:
        return "Wait at least 60 seconds before requesting another sign-in email."
    if "pippa_auth_address_hour" in combined or "pippa_auth_address_day" in combined:
        return (
            "This address has reached its sign-in email allowance. "
            "Use an existing valid email or try again later."
        )
    if "pippa_auth_global_hour" in combined:
        return "PIPPA's sign-in email service is busy. Please try again later."
    if "pippa_app_auth_required" in combined:
        return "PIPPA's protected sign-in service is not configured. Access remains closed."
    if "captcha" in combined:
        return "The security check expired or could not be verified. Complete it again and retry."

    if "pydantic_core" in combined or "no module named" in combined:
        return (
            "PIPPA's local Python environment is incomplete or incompatible. "
            "Close this window and restart PIPPA using Start PIPPA.bat so its required packages are repaired."
        )
    if 429 in statuses or "rate limit" in combined or "over_email_send_rate_limit" in combined:
        return (
            "Too many sign-in emails were requested. Wait at least 60 seconds, then request one new email."
        )
    if "smtp" in combined or "email_address_not_authorized" in combined:
        return (
            "The sign-in request reached Supabase, but its email service rejected the message. "
            "Check the configured sender and SMTP account, then try again."
        )
    if any(status in statuses for status in (500, 502, 503, 504)):
        return (
            "The sign-in email service is temporarily unavailable. Wait a moment and try once more."
        )
    return (
        "PIPPA could not send the sign-in email. Check the address, wait at least 60 seconds, "
        "and try once more. If it still fails, review the latest Supabase Auth log entry."
    )


@dataclass
class AuthenticatedSession:
    client: Any
    user_id: str
    email: str

    def sign_out(self) -> None:
        """Revoke only this browser session, not the user's other devices."""
        self.client.auth.sign_out(options={"scope": "local"})

    def revalidate(self) -> None:
        """Confirm that active server state still represents the same user."""
        try:
            verified = self.client.auth.get_user()
            user = getattr(verified, "user", None)
            user_id = str(getattr(user, "id", "") or "").strip()
            email = str(getattr(user, "email", "") or "").strip().lower()
            active_user_id = self.client.rpc("pippa_active_user_id", {}).execute().data
            if active_user_id != self.user_id:
                raise AuthenticationError("Your sign-in is no longer valid. Please sign in again.")
        except Exception as exc:
            raise AuthenticationError("Your sign-in is no longer valid. Please sign in again.") from exc
        if not user_id or not email or user_id != self.user_id or email != self.email:
            raise AuthenticationError("Your sign-in changed or expired. Please sign in again.")

    def rememberable_tokens(self) -> dict[str, str]:
        """Return only the provider session material needed to restore this browser.

        The caller must encrypt this payload before placing it in browser storage.
        Email and user identity are deliberately not used as proof of sign-in.
        """
        session_response = self.client.auth.get_session()
        # supabase-py returns Session directly. The wrapper fallback keeps this
        # tolerant of compatible clients that return an AuthResponse instead.
        session = getattr(session_response, "session", None) or session_response
        access_token = str(getattr(session, "access_token", "") or "")
        refresh_token = str(getattr(session, "refresh_token", "") or "")
        if not access_token or not refresh_token:
            raise AuthenticationError("PIPPA could not prepare this browser to stay signed in.")
        return {"access_token": access_token, "refresh_token": refresh_token}


class SupabaseAuth:
    """Passwordless Supabase Auth without any service-role credentials."""

    def __init__(
        self,
        url: str,
        publishable_key: str,
        redirect_url: str,
        rate_limit_secret: str = "",
    ):
        self.url = url
        self.publishable_key = publishable_key
        self.redirect_url = redirect_url.rstrip("/")
        self.rate_limit_secret = rate_limit_secret

    def _client(self):
        try:
            from supabase import create_client
        except ImportError as exc:
            raise AuthenticationError(
                "Supabase support is not installed. Run the PIPPA launcher to install the updated requirements."
            ) from exc
        return create_client(self.url, self.publishable_key)

    def request_magic_link(
        self,
        email: str,
        captcha_token: str = "",
        request_id: str = "",
    ) -> None:
        try:
            client = self._client()
            request_id = request_id or new_request_id()
            if self.rate_limit_secret:
                client.rpc(
                    "pippa_authorize_sign_in",
                    {
                        "p_email_key": sign_in_email_key(email, self.rate_limit_secret),
                        "p_request_id": request_id,
                        "p_app_secret": self.rate_limit_secret,
                    },
                ).execute()
            options = {
                "email_redirect_to": self.redirect_url,
                "should_create_user": True,
            }
            if captcha_token:
                options["captcha_token"] = captcha_token
            client.auth.sign_in_with_otp(
                {
                    "email": email,
                    "options": options,
                }
            )
        except Exception as exc:
            raise AuthenticationError(_safe_magic_link_error(exc)) from exc

    def verify_email_code(self, email: str, code: str) -> AuthenticatedSession:
        try:
            client = self._client()
            response = client.auth.verify_otp(
                {"email": email, "token": code, "type": "email"}
            )
            return self._authenticated_session(client, response)
        except AuthenticationError:
            raise
        except Exception as exc:
            raise AuthenticationError(
                "That sign-in code is invalid or has expired. Request a new email and try again."
            ) from exc

    def verify_token_hash(self, token_hash: str, verification_type: str) -> AuthenticatedSession:
        if verification_type != "email":
            raise AuthenticationError("This sign-in link type is not supported by PIPPA.")
        try:
            client = self._client()
            response = client.auth.verify_otp(
                {"token_hash": token_hash, "type": "email"}
            )
            return self._authenticated_session(client, response)
        except AuthenticationError:
            raise
        except Exception as exc:
            raise AuthenticationError(
                "That sign-in link is invalid, expired or has already been used. Request a new link."
            ) from exc

    def restore_session(self, access_token: str, refresh_token: str) -> AuthenticatedSession:
        """Restore an encrypted, opt-in browser session and verify it with Supabase."""
        if not access_token or not refresh_token:
            raise AuthenticationError("The saved browser sign-in is incomplete.")
        try:
            client = self._client()
            response = client.auth.set_session(access_token, refresh_token)
            # Do not trust identity data from browser storage. Supabase validates the
            # restored credentials before PIPPA accepts the session.
            if not getattr(response, "session", None):
                raise AuthenticationError("The saved browser sign-in could not be restored.")
            verified = client.auth.get_user()
            user = getattr(verified, "user", None)
            user_id = str(getattr(user, "id", "") or "").strip()
            email = str(getattr(user, "email", "") or "").strip().lower()
            if not user_id or not email:
                raise AuthenticationError("The saved browser sign-in could not be verified.")
            restored = AuthenticatedSession(client=client, user_id=user_id, email=email)
            restored.revalidate()
            return restored
        except AuthenticationError:
            raise
        except Exception as exc:
            raise AuthenticationError("Your saved sign-in has expired. Please sign in again.") from exc

    @staticmethod
    def _authenticated_session(client: Any, response: Any) -> AuthenticatedSession:
        session = getattr(response, "session", None)
        user = getattr(response, "user", None) or getattr(session, "user", None)
        user_id = str(getattr(user, "id", "") or "").strip()
        email = str(getattr(user, "email", "") or "").strip().lower()
        if not session or not user_id or not email:
            raise AuthenticationError("Supabase did not return a complete authenticated session.")
        return AuthenticatedSession(client=client, user_id=user_id, email=email)
