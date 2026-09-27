from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path

import streamlit as st

from pippa.answering import answer_question
from pippa.auth import (
    AuthenticationError,
    REMEMBERED_INTENT_COOKIE,
    REMEMBERED_SESSION_COOKIE,
    REMEMBERED_SESSION_SECONDS,
    SupabaseAuth,
    auth_callback_allowed,
    clear_remembered_session_cookies,
    logout_safely,
    parse_remembered_session_payload,
)
from pippa.captcha import turnstile_token
from pippa.config import DB_PATH, KNOWLEDGE_DIR
from pippa.governance import context_for, history_csv, personal_metrics
from pippa.knowledge import KnowledgeBase, corpus_revision
from pippa.limits import (
    AUTH_EMAIL_RESEND_SECONDS,
    MAX_QUESTION_CHARS,
    QuestionCapacity,
    QuestionCapacityError,
    QuestionQuotaError,
    QuestionValidationError,
    new_request_id,
    validate_question,
)
from pippa.repository import LocalConversationStore, SupabaseConversationStore
from pippa.runtime_config import RuntimeSettings
from pippa.suggestions import suggestions_for
from pippa.validation import valid_email


st.set_page_config(page_title="PIPPA", page_icon="🔷", layout="wide", initial_sidebar_state="expanded")
style_path = Path(__file__).parent / "assets" / "style.css"
# Load the stylesheet on every script rebuild so authentication controls share accessible contrast.
st.markdown(f"<style>{style_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


@st.cache_resource
def load_knowledge(revision: str) -> KnowledgeBase:
    return KnowledgeBase(KNOWLEDGE_DIR)


@st.cache_resource
def question_capacity() -> QuestionCapacity:
    return QuestionCapacity()


def clear_user_state() -> None:
    for key in (
        "user_email",
        "supabase_session",
        "pending_auth_email",
        "latest",
        "pending_question",
        "question_input",
        "remember_browser",
        "remember_warning",
        "usage_open_recorded",
        "usage_open_id",
        "pending_request_id",
        "pending_request_question",
        "last_auth_request_at",
        "captcha_generation",
    ):
        st.session_state.pop(key, None)


def select_example(question: str) -> None:
    """Populate the question widget before Streamlit rebuilds the form."""
    st.session_state.question_input = question


def source_cards(hits) -> None:
    seen = set()
    for hit in hits:
        source = hit.passage
        if source.clause_id in seen:
            continue
        seen.add(source.clause_id)
        st.markdown(
            f"""<div class="source-card"><div class="source-id">{html.escape(source.clause_id)}</div>
            <div><strong>{html.escape(source.title)}</strong> · Version {html.escape(source.version)} · Effective {html.escape(source.effective_date)}</div>
            <div class="quote">“{html.escape(source.text)}”</div></div>""",
            unsafe_allow_html=True,
        )


settings = RuntimeSettings.from_sources()
kb = load_knowledge(corpus_revision(KNOWLEDGE_DIR))
if getattr(settings, "supabase_key_is_unsafe", False):
    st.error(
        "Unsafe Supabase configuration: PIPPA received a secret/service-role key. "
        "Remove it and use only the browser-safe publishable key."
    )
    st.stop()
if settings.configuration_errors:
    for configuration_error in settings.configuration_errors:
        st.error(configuration_error)
    st.caption(
        "Local demonstration mode must be enabled explicitly with PIPPA_LOCAL_DEMO=true. "
        "Public access additionally requires verified sign-in, Turnstile and durable rate limiting."
    )
    st.stop()
auth = (
    SupabaseAuth(
        settings.supabase_url,
        settings.supabase_publishable_key,
        settings.app_url,
        settings.rate_limit_secret,
    )
    if settings.supabase_enabled
    else None
)

# Streamlit clears its server-side session state on a browser refresh.  The
# optional encrypted cookie below is deliberately separate from normal auth:
# it is opt-in, contains no asserted email identity, expires after 14 days,
# and is always revalidated with Supabase before PIPPA uses it.
remembered_cookie = None
if settings.remembered_sign_in_enabled:
    try:
        from streamlit_cookies_manager import EncryptedCookieManager

        remembered_cookie = EncryptedCookieManager(
            prefix="pippa/",
            password=settings.cookie_password,
        )
        if not remembered_cookie.ready():
            st.stop()
    except ImportError:
        st.warning("The optional remembered sign-in feature is unavailable until PIPPA is redeployed with its updated requirements.")


def clear_remembered_session() -> bool:
    if remembered_cookie is None:
        return True
    try:
        clear_remembered_session_cookies(remembered_cookie)
        return True
    except Exception:
        return False


def remember_session_if_requested(authenticated) -> None:
    if remembered_cookie is None:
        return
    requested = st.session_state.get("remember_browser", False) or remembered_cookie.get(REMEMBERED_INTENT_COOKIE) == "yes"
    if not requested:
        return
    try:
        payload = {
            "tokens": authenticated.rememberable_tokens(),
            "expires_at": int(time.time()) + REMEMBERED_SESSION_SECONDS,
        }
        remembered_cookie[REMEMBERED_SESSION_COOKIE] = json.dumps(payload)
        remembered_cookie.pop(REMEMBERED_INTENT_COOKIE, None)
        remembered_cookie.save()
    except Exception:
        # A normal verified session remains active even if optional browser
        # persistence is not available. Do not expose credential details.
        st.session_state.remember_warning = "PIPPA could not keep this browser signed in. Your current sign-in still works."


def capture_remember_preference() -> None:
    """Carry a non-sensitive browser preference through the email-link callback."""
    if remembered_cookie is None:
        return
    try:
        if st.session_state.get("remember_browser", False):
            remembered_cookie[REMEMBERED_INTENT_COOKIE] = "yes"
        else:
            remembered_cookie.pop(REMEMBERED_INTENT_COOKIE, None)
        remembered_cookie.save()
    except Exception:
        st.session_state.remember_warning = (
            "PIPPA could not save the remembered-browser preference. "
            "You can still sign in for this browser session."
        )


def restore_remembered_session() -> None:
    if remembered_cookie is None or auth is None:
        return
    raw_payload = remembered_cookie.get(REMEMBERED_SESSION_COOKIE)
    if not raw_payload:
        return
    try:
        access_token, refresh_token, expires_at = parse_remembered_session_payload(raw_payload)
        authenticated = auth.restore_session(access_token, refresh_token)
        st.session_state.supabase_session = authenticated
        st.session_state.user_email = authenticated.email
        # set_session may rotate an expired access/refresh pair. Persist the
        # replacement tokens but retain the original fixed 14-day deadline.
        remembered_cookie[REMEMBERED_SESSION_COOKIE] = json.dumps(
            {"tokens": authenticated.rememberable_tokens(), "expires_at": expires_at}
        )
        remembered_cookie.save()
    except Exception:
        clear_remembered_session()

# A server-readable token hash is supplied by the configured Supabase email
# template. It avoids putting access and refresh tokens in the browser URL.
if settings.supabase_enabled and not auth_callback_allowed(
    "supabase_session" in st.session_state,
    str(st.query_params.get("token_hash", "")).strip(),
    str(st.query_params.get("type", "")).strip(),
) and st.query_params.get("token_hash") and "supabase_session" in st.session_state:
    st.query_params.clear()
    st.session_state.auth_error = (
        "PIPPA ignored a sign-in link because this tab is already signed in. "
        "Sign out first if you intend to use another account."
    )
    st.rerun()

if settings.supabase_enabled and "supabase_session" not in st.session_state:
    token_hash = str(st.query_params.get("token_hash", "")).strip()
    verification_type = str(st.query_params.get("type", "")).strip()
    if token_hash:
        try:
            with st.spinner("Verifying your secure PIPPA sign-in link…"):
                authenticated = auth.verify_token_hash(token_hash, verification_type)
            st.session_state.supabase_session = authenticated
            st.session_state.user_email = authenticated.email
            remember_session_if_requested(authenticated)
            st.session_state.pop("pending_auth_email", None)
            st.query_params.clear()
            st.rerun()
        except AuthenticationError as exc:
            st.session_state.auth_error = str(exc)
            st.query_params.clear()

if settings.supabase_enabled and "supabase_session" not in st.session_state and not st.query_params.get("token_hash"):
    restore_remembered_session()

# Revalidate active identity on every Streamlit rerun. A stale, revoked or
# unexpectedly changed provider session must not remain usable in server state.
if settings.supabase_enabled and "supabase_session" in st.session_state:
    try:
        st.session_state.supabase_session.revalidate()
    except AuthenticationError as exc:
        cookie_cleared = clear_remembered_session()
        clear_user_state()
        st.session_state.auth_error = str(exc)
        if not cookie_cleared:
            st.session_state.auth_error += (
                " PIPPA cleared the active session, but the browser cookie could not be removed; "
                "clear this site's browser data before signing in again."
            )

# Never allow a prior local-prototype identity to become a Supabase identity.
if settings.supabase_enabled and "supabase_session" not in st.session_state:
    st.session_state.pop("user_email", None)

with st.sidebar:
    st.markdown("## PIPPA")
    st.caption("Policy, Instructions, Processes & Procedures Assistant")
    if "user_email" not in st.session_state:
        st.markdown("### Sign in to continue")
        if settings.supabase_enabled:
            st.caption("Secure passwordless sign-in. We will email you a one-time link and code.")
            if remembered_cookie is not None:
                st.checkbox(
                    "Keep me signed in on this browser for 14 days",
                    key="remember_browser",
                    help="Use this only on a personal or otherwise trusted browser. Sign out clears it immediately.",
                )
            email = st.text_input("Work or personal email", placeholder="you@example.com")
            # Supabase CAPTCHA protection applies to the OTP endpoint even while
            # PIPPA is in private pre-publication mode. Render Turnstile whenever
            # its public site key is configured; PIPPA_PUBLIC_ACCESS controls
            # publication readiness, not whether authentication supplies the
            # provider-required CAPTCHA token.
            captcha_required = bool(settings.turnstile_site_key)
            captcha_token = (
                turnstile_token(
                    settings.turnstile_site_key,
                    key=f"pippa-turnstile-{st.session_state.get('captcha_generation', 0)}",
                )
                if captcha_required
                else ""
            )
            elapsed = time.time() - float(st.session_state.get("last_auth_request_at", 0.0))
            resend_remaining = max(0, AUTH_EMAIL_RESEND_SECONDS - int(elapsed))
            if resend_remaining:
                st.caption(
                    f"PIPPA will accept another email request in about {resend_remaining} seconds."
                )
            request_email = st.button(
                "Email my secure sign-in link",
                type="primary",
                use_container_width=True,
                disabled=captcha_required and not captcha_token,
            )
            if request_email:
                if valid_email(email):
                    try:
                        capture_remember_preference()
                        # Turnstile tokens are single-use. Every attempted provider
                        # request gets a fresh widget on the following rerun.
                        st.session_state.captcha_generation = int(
                            st.session_state.get("captcha_generation", 0)
                        ) + 1
                        auth.request_magic_link(
                            email.strip().lower(),
                            captcha_token=captcha_token,
                            request_id=new_request_id(),
                        )
                        st.session_state.pending_auth_email = email.strip().lower()
                        st.session_state.last_auth_request_at = time.time()
                        st.session_state.pop("auth_error", None)
                        st.rerun()
                    except AuthenticationError as exc:
                        st.session_state.auth_error = str(exc)
                        st.rerun()
                else:
                    st.error("Enter a valid email address.")
            if "pending_auth_email" in st.session_state:
                st.success(
                    "If that address can receive PIPPA sign-in messages, its email is on the way."
                )
                st.caption("Open the link in the email. If the link does not work, enter the complete code below.")
                with st.form("email-code-form", clear_on_submit=True):
                    code = st.text_input(
                        "Email verification code",
                        max_chars=10,
                        placeholder="Enter the code from your email",
                    )
                    verify_code = st.form_submit_button("Verify code", use_container_width=True)
                if verify_code:
                    if re.fullmatch(r"\d{6,10}", code.strip()):
                        try:
                            authenticated = auth.verify_email_code(
                                st.session_state.pending_auth_email,
                                code.strip(),
                            )
                            st.session_state.supabase_session = authenticated
                            st.session_state.user_email = authenticated.email
                            remember_session_if_requested(authenticated)
                            st.session_state.pop("pending_auth_email", None)
                            st.session_state.pop("auth_error", None)
                            st.rerun()
                        except AuthenticationError as exc:
                            st.error(str(exc))
                    else:
                        st.error("Enter the complete numeric code from the email.")
            if "auth_error" in st.session_state:
                st.error(st.session_state.pop("auth_error"))
        else:
            st.caption("Local prototype sign-in. Connect Supabase to verify email ownership.")
            email = st.text_input("Work or personal email", placeholder="you@example.com")
            if st.button("Continue", type="primary", use_container_width=True):
                if valid_email(email):
                    st.session_state.user_email = email.strip().lower()
                    st.rerun()
                else:
                    st.error("Enter a valid email address.")
    else:
        st.success(f"Signed in as\n\n{st.session_state.user_email}")
        if "auth_error" in st.session_state:
            st.warning(st.session_state.pop("auth_error"))
        if "remember_warning" in st.session_state:
            st.warning(st.session_state.pop("remember_warning"))
        if st.button("Sign out", use_container_width=True):
            logout_result = logout_safely(
                st.session_state.get("supabase_session") if settings.supabase_enabled else None,
                remembered_cookie,
                clear_user_state,
            )
            warnings = []
            if logout_result.remote_revocation_failed:
                warnings.append("PIPPA could not confirm remote session revocation.")
            if logout_result.cookie_cleanup_failed:
                warnings.append(
                    " The active session was cleared, but the browser cookie could not be removed. "
                    "Clear this site's browser data before signing in again."
                )
            if warnings:
                st.session_state.signed_out_warning = " ".join(warnings).strip()
            st.rerun()
    st.divider()
    st.caption(f"Knowledge status: {len(kb.documents)} current documents · {len(kb.passages)} controlled clauses")
    st.caption("Answer mode: evidence-first policy guidance")
    st.caption("Identity: " + ("Verified by Supabase" if settings.supabase_enabled else "Local demonstration only"))

if "user_email" not in st.session_state:
    if "signed_out_warning" in st.session_state:
        st.warning(st.session_state.pop("signed_out_warning"))
    st.markdown("""<div class="pippa-hero"><h1>Meet PIPPA</h1><p>Clear, grounded guidance from the policies that govern your work.</p></div>""", unsafe_allow_html=True)
    left, right = st.columns([1.15, .85], gap="large")
    with left:
        st.subheader("Ask naturally. Act confidently.")
        st.write("PIPPA finds the controlling clause, explains it in plain English, suggests practical next steps and shows the exact source used.")
        st.markdown('<span class="pill">Plain English</span><span class="pill">Exact quotations</span><span class="pill">Source citations</span><span class="pill">Controlled escalation</span>', unsafe_allow_html=True)
    with right:
        st.markdown('<div class="notice"><strong>Showcase environment</strong><br>This prototype uses fictional UAE policies and synthetic company data. It is not operational, legal or financial advice.</div>', unsafe_allow_html=True)
    st.stop()

if settings.supabase_enabled:
    session = st.session_state.supabase_session
    store = SupabaseConversationStore(
        session.client, session.user_id, settings.rate_limit_secret
    )
else:
    store = LocalConversationStore(DB_PATH)

# One event per browser session distinguishes a visit from a policy question.
# If the analytics migration has not yet been applied, it must never interrupt
# sign-in, retrieval, answer storage or the existing reviewer workflow.
if settings.supabase_enabled and not st.session_state.get("usage_open_recorded"):
    if "usage_open_id" not in st.session_state:
        st.session_state.usage_open_id = new_request_id()
    try:
        store.record_usage_event(
            "app_opened", idempotency_key=st.session_state.usage_open_id
        )
        st.session_state.usage_open_recorded = True
    except Exception:
        st.session_state.analytics_warning = (
            "PIPPA could not record this visit. Usage reporting may be incomplete."
        )

st.markdown("""<div class="pippa-hero"><h1>How can I help?</h1><p>Describe the situation in your own words. I’ll find the relevant procedure and show my sources.</p></div>""", unsafe_allow_html=True)

ask_tab, history_tab, governance_tab = st.tabs(["Ask PIPPA", "My history", "Trust & governance"])

with ask_tab:
    if "analytics_warning" in st.session_state:
        st.warning(st.session_state.pop("analytics_warning"))
    policy_areas = ["All policy areas", *kb.functions]
    selected_policy_area = st.pills(
        "Policy area",
        policy_areas,
        default="All policy areas",
        selection_mode="single",
        help="Choose an area to browse verified example questions. PIPPA still checks the complete policy library when answering.",
    ) or "All policy areas"
    if st.session_state.get("displayed_policy_area") != selected_policy_area:
        st.session_state.displayed_policy_area = selected_policy_area
        st.session_state.pop("latest", None)
    if selected_policy_area == "All policy areas":
        st.caption("Browse cross-functional examples. Every answer is checked against the complete current policy library.")
    else:
        st.caption(
            f"Showing verified examples for **{selected_policy_area}**. "
            "Questions are still checked against the complete library, including cross-functional controls."
        )
    st.write("Try a scenario:")
    examples = suggestions_for(selected_policy_area)
    columns = st.columns(2)
    for index, example in enumerate(examples):
        columns[index % 2].button(
            example.text,
            key=f"example-{selected_policy_area}-{index}",
            use_container_width=True,
            on_click=select_example,
            args=(example.text,),
        )

    st.caption(
        "Privacy: questions and answers are retained for 30 days. A designated reviewer may see "
        "the question when an answer is incomplete or you request review. Administrators see "
        "your email and activity counts, not your answer text. Do not enter real confidential, "
        "personal or credential information."
    )
    with st.form("question-form", clear_on_submit=False):
        question = st.text_area(
            "Your question",
            key="question_input",
            height=110,
            max_chars=MAX_QUESTION_CHARS + 1,
            placeholder="Tell PIPPA what happened, including dates, amounts and anything unusual.",
        )
        submitted = st.form_submit_button("Ask PIPPA", type="primary", use_container_width=True)

    if submitted:
        try:
            validated_question = validate_question(question)
        except QuestionValidationError as exc:
            st.warning(str(exc))
        else:
            if st.session_state.get("pending_request_question") != validated_question:
                st.session_state.pending_request_question = validated_question
                st.session_state.pending_request_id = new_request_id()
            request_id = st.session_state.pending_request_id
            try:
                with question_capacity().slot():
                    store.authorize_question(
                        st.session_state.user_email, request_id
                    )
                    with st.spinner("Checking the current controlled documents…"):
                        result = answer_question(validated_question, kb, settings)
                    source_ids = [hit.passage.clause_id for hit in result.hits]
                    governance = context_for(result, kb)
                    conversation_id = store.save(
                        st.session_state.user_email,
                        validated_question,
                        result.body,
                        result.mode,
                        source_ids,
                        governance,
                        request_id=request_id,
                    )
                st.session_state.latest = (
                    conversation_id,
                    validated_question,
                    result,
                )
                st.session_state.pop("pending_request_id", None)
                st.session_state.pop("pending_request_question", None)
            except (QuestionQuotaError, QuestionCapacityError) as exc:
                st.warning(str(exc))
            except Exception:
                st.error(
                    "PIPPA could not complete and save this request safely. Please try again. "
                    "A retry of the same request will not be counted twice."
                )

    if "latest" in st.session_state:
        conversation_id, latest_question, result = st.session_state.latest
        st.caption(f"Response mode: {result.mode}")
        if result.status == "unavailable":
            st.warning("PIPPA could not find sufficient current policy evidence to answer this safely.")
        elif result.status == "partial":
            st.info("PIPPA found relevant policy detail, but has deliberately not treated it as a complete answer.")
        st.markdown(result.body)
        if result.grounded:
            st.subheader("Policy evidence")
            source_cards(result.hits)
        elif result.hits:
            st.subheader("Related material reviewed — not sufficient to answer")
            source_cards(result.hits)
        left, middle, right = st.columns([1, 1, 5])
        if conversation_id is not None:
            if left.button("👍 Helpful", key=f"up-{conversation_id}"):
                try:
                    store.set_feedback(conversation_id, st.session_state.user_email, "helpful")
                    st.toast("Feedback saved")
                except Exception:
                    st.error("PIPPA could not save your feedback. Please try again.")
            if middle.button("👎 Review", key=f"down-{conversation_id}"):
                try:
                    store.set_feedback(conversation_id, st.session_state.user_email, "needs_review")
                    st.toast("Marked for human review")
                except Exception:
                    st.error("PIPPA could not send this item for review. Please try again.")
            identity_wording = "verified user" if settings.supabase_enabled else "local demonstration identity"
            right.caption(f"Feedback is linked to this {identity_wording} and response.")
        else:
            right.caption("Feedback is unavailable because this response was not saved.")

with history_tab:
    if "history_notice" in st.session_state:
        st.success(st.session_state.pop("history_notice"))
    try:
        rows = store.history(st.session_state.user_email)
    except Exception:
        rows = []
        st.error("PIPPA could not load your history. Your current sign-in remains active; please try again.")
    if not rows:
        st.info("Your questions will appear here after you ask PIPPA.")
    else:
        try:
            export_rows = store.export_history(st.session_state.user_email)
            st.download_button(
                "Download my retained history",
                data=history_csv(export_rows),
                file_name="pippa-history.csv",
                mime="text/csv",
                use_container_width=True,
            )
        except Exception:
            st.warning("PIPPA could not prepare your history download right now.")
    for row in rows:
        conversation_id, created_at, question, body, mode, source_ids, feedback = row
        with st.expander(question, expanded=False):
            st.caption(f"{created_at[:16].replace('T', ' ')} UTC · {mode} · Sources: {source_ids or 'none'}")
            st.markdown(body)
            if feedback:
                st.caption(f"Your feedback: {feedback.replace('_', ' ')}")
    st.caption("Question and answer content is automatically removed after 30 days.")
    with st.expander("Delete my history"):
        st.write(
            "This permanently removes your retained questions and answers. "
            "Non-content security and usage records may be retained for governance."
        )
        confirm_delete = st.checkbox(
            "I understand that my retained question and answer history will be deleted.",
            key="confirm_history_delete",
        )
        if st.button(
            "Delete my retained history",
            disabled=not confirm_delete,
            use_container_width=True,
        ):
            try:
                deleted_count = store.delete_my_history(st.session_state.user_email)
                st.session_state.pop("latest", None)
                st.session_state.history_notice = (
                    f"Deleted {deleted_count} retained PIPPA conversation"
                    f"{'s' if deleted_count != 1 else ''}."
                )
                st.rerun()
            except Exception:
                st.error("PIPPA could not delete your history. Nothing was reported as deleted; please try again.")

with governance_tab:
    st.subheader("Why this answer should be trusted")
    st.markdown("""
- Only documents marked **CURRENT** are loaded into normal retrieval.
- Every answer displays the exact policy wording and clause identifiers used.
- Weak retrieval produces a controlled refusal instead of a confident guess.
- The assistant is instructed never to invent authority, thresholds, dates or procedures.
- Each signed-in user receives an individual history and can flag a response for review.
- The library includes a maintained evaluation set for regression testing after changes.
    """)
    st.markdown('<div class="notice"><strong>Human-in-the-loop boundary</strong><br>A real deployment must route low-confidence, conflicting, high-risk and policy-owner questions to an authorised reviewer. The MVP demonstrates this behaviour; it does not replace accountable decision-makers.</div>', unsafe_allow_html=True)
    st.divider()
    st.subheader("Your governance signals")
    try:
        governance_rows = store.history(st.session_state.user_email, limit=100)
    except Exception:
        governance_rows = []
        st.warning("PIPPA could not load your personal governance signals right now.")
    metrics = personal_metrics(governance_rows)
    metric_columns = st.columns(4)
    metric_columns[0].metric("Questions", metrics["questions"])
    metric_columns[1].metric("Evidence complete", metrics["evidence_complete"])
    metric_columns[2].metric("Needs attention", metrics["needs_attention"])
    metric_columns[3].metric("You flagged", metrics["flagged_for_review"])
    st.caption(
        "These figures use only your latest 100 retained conversations. "
        "Other employees cannot see them."
    )

    if settings.supabase_enabled:
        try:
            reviewer = store.is_reviewer()
        except Exception:
            reviewer = False
        if reviewer:
            st.subheader("Private reviewer queue")
            st.caption("This queue contains only incomplete answers and responses explicitly marked for review. Access is controlled by Supabase reviewer permissions.")
            try:
                review_items = store.reviewer_queue()
            except Exception:
                review_items = []
                st.info("The reviewer queue will activate after the secure governance migration has been applied in Supabase.")
            if review_items:
                st.metric("Open review items", len(review_items))
                for item in review_items:
                    policy_area = item.get("policy_area") or "Not classified (pre-governance record)"
                    status = item.get("review_status") or "new"
                    with st.expander(f"{policy_area} · {item.get('mode', 'Unclassified')} · {status}"):
                        st.write(item.get("question", ""))
                        st.caption(f"Suggested owner: {item.get('recommended_owner') or 'Use the policy owner or line manager'}")
                        st.caption(f"Sources: {', '.join(item.get('source_ids') or []) or 'none'} · Feedback: {item.get('feedback') or 'none'}")
                        left, right = st.columns(2)
                        if left.button(
                            "Mark in review",
                            key=f"review-{item['id']}",
                            disabled=status == "in_review",
                        ):
                            try:
                                store.set_review_status(item["id"], "in_review")
                                st.rerun()
                            except Exception:
                                st.error("PIPPA could not update this review item. Please try again.")
                        if right.button("Resolve", key=f"resolve-{item['id']}"):
                            try:
                                store.set_review_status(item["id"], "resolved")
                                st.rerun()
                            except Exception:
                                st.error("PIPPA could not resolve this review item. Please try again.")
            else:
                st.info("There are no open reviewer items.")
        else:
            st.info("A designated policy reviewer can view cross-user review items only after being assigned in Supabase. Your personal history remains private.")

        try:
            administrator = store.is_administrator()
        except Exception:
            administrator = False
        if administrator:
            st.divider()
            st.subheader("Private PIPPA Insights")
            st.caption(
                "Administrator-only, read-only engagement reporting. It records app opens and "
                "questions from the point the Insights migration is enabled; it does not display "
                "employees’ question or answer text here. Review-flag counts cover currently "
                "retained conversations; other activity counts cover retained non-content events."
            )
            try:
                user_usage = store.administrator_usage_summary()
                policy_usage = store.administrator_policy_usage()
            except Exception:
                user_usage, policy_usage = [], []
                st.info("Insights will activate after the secure Insights migration has been applied in Supabase.")
            if user_usage:
                total_opens = sum(int(row.get("app_opens", 0) or 0) for row in user_usage)
                total_questions = sum(int(row.get("questions", 0) or 0) for row in user_usage)
                total_attention = sum(int(row.get("needs_attention", 0) or 0) for row in user_usage)
                insight_metrics = st.columns(4)
                insight_metrics[0].metric("Signed-in users", len(user_usage))
                insight_metrics[1].metric("App opens", total_opens)
                insight_metrics[2].metric("Questions", total_questions)
                insight_metrics[3].metric("Needs attention", total_attention)
                st.markdown("**User activity**")
                st.dataframe(user_usage, use_container_width=True, hide_index=True)
                if policy_usage:
                    st.markdown("**Policy-area activity**")
                    st.dataframe(policy_usage, use_container_width=True, hide_index=True)
            elif administrator:
                st.info("No Insights activity has been recorded yet. New signed-in visits and questions will appear here after the migration is enabled.")
    else:
        st.info("The cross-user reviewer queue is available only with verified Supabase sign-in. Local demonstration mode keeps records on this device.")
    st.markdown('<p class="synthetic">All organisations, people, policies, approval limits and scenarios in this prototype are fictional.</p>', unsafe_allow_html=True)


