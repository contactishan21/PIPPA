from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RuntimeSettings:
    """External-service settings loaded from environment or Streamlit secrets."""

    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    app_url: str = "http://localhost:8501"
    cookie_password: str = ""
    rate_limit_secret: str = ""
    turnstile_site_key: str = ""
    local_demo_enabled: bool = False
    public_access_enabled: bool = False
    top_k: int = 5
    minimum_score: float = 2.0

    @classmethod
    def from_sources(cls) -> "RuntimeSettings":
        secrets: dict[str, Any] = {}
        try:
            import streamlit as st

            secrets = dict(st.secrets)
        except Exception:
            pass

        def value(name: str, default: str = "") -> str:
            return os.getenv(name, "").strip() or str(secrets.get(name, default)).strip()

        def enabled(name: str, default: bool = False) -> bool:
            raw = value(name, "true" if default else "false").lower()
            return raw in {"1", "true", "yes", "on"}

        local_demo_enabled = enabled("PIPPA_LOCAL_DEMO")
        # The Windows launcher deliberately enables an offline demo for recording
        # and local review.  A developer may also have hosted Supabase values in
        # .streamlit/secrets.toml; those must not switch that explicit demo back
        # to verified sign-in or require its production write secret.
        use_local_demo = local_demo_enabled and not enabled("PIPPA_PUBLIC_ACCESS")

        return cls(
            openai_api_key=value("OPENAI_API_KEY"),
            openai_model=value("OPENAI_MODEL", "gpt-5-mini"),
            supabase_url="" if use_local_demo else value("SUPABASE_URL"),
            supabase_publishable_key=(
                ""
                if use_local_demo
                else (value("SUPABASE_PUBLISHABLE_KEY") or value("SUPABASE_ANON_KEY"))
            ),
            app_url=value("PIPPA_APP_URL", "http://localhost:8501").rstrip("/"),
            cookie_password=value("PIPPA_COOKIE_PASSWORD"),
            rate_limit_secret=value("PIPPA_RATE_LIMIT_SECRET"),
            turnstile_site_key=value("PIPPA_TURNSTILE_SITE_KEY"),
            local_demo_enabled=local_demo_enabled,
            public_access_enabled=enabled("PIPPA_PUBLIC_ACCESS"),
        )

    @property
    def ai_enabled(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def supabase_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_publishable_key)

    @property
    def remembered_sign_in_enabled(self) -> bool:
        """Only enable browser persistence when an explicit encryption secret exists."""
        return self.supabase_enabled and len(self.cookie_password) >= 32

    @property
    def supabase_key_is_unsafe(self) -> bool:
        """Reject secret/service-role keys before a client can be created."""
        key = self.supabase_publishable_key.strip()
        if key.startswith("sb_secret_"):
            return True
        if key.count(".") == 2:
            try:
                payload = key.split(".")[1]
                payload += "=" * (-len(payload) % 4)
                claims = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
                return claims.get("role") == "service_role"
            except Exception:
                return False
        return False

    @property
    def configuration_errors(self) -> tuple[str, ...]:
        """Return publication-safe configuration errors without exposing secrets."""
        errors: list[str] = []
        if not self.supabase_enabled and not self.local_demo_enabled:
            errors.append(
                "Verified sign-in is not configured. PIPPA has stopped instead of using an unverified identity."
            )
        if self.supabase_enabled and len(self.rate_limit_secret) < 32:
            errors.append(
                "Verified sign-in requires the Phase 3 application-write secret of at least 32 characters."
            )
        if self.public_access_enabled:
            if not self.supabase_enabled:
                errors.append("Public access requires verified Supabase authentication.")
            if not self.turnstile_site_key:
                errors.append("Public access requires the configured Turnstile site key.")
        return tuple(errors)
