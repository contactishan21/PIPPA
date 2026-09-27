from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from .storage import authorize_question, delete_history, history, initialise, save, set_feedback
from .governance import GovernanceContext
from .limits import QuestionQuotaError, validate_question


class ConversationStore(Protocol):
    def authorize_question(self, email: str, request_id: str) -> None: ...

    def save(self, email: str, question: str, answer: str, mode: str, source_ids: list[str], governance: GovernanceContext | None = None, request_id: str = "") -> str | int: ...

    def history(self, email: str, limit: int = 20) -> list[tuple]: ...

    def export_history(self, email: str) -> list[tuple]: ...

    def set_feedback(self, conversation_id: str | int, email: str, value: str) -> None: ...

    def delete_my_history(self, email: str) -> int: ...

    def is_reviewer(self) -> bool: ...

    def reviewer_queue(self, limit: int = 100) -> list[dict[str, Any]]: ...

    def set_review_status(self, conversation_id: str | int, value: str) -> None: ...

    def record_usage_event(self, event_type: str, idempotency_key: str = "", policy_area: str = "", answer_status: str = "", conversation_id: str | int | None = None) -> None: ...

    def is_administrator(self) -> bool: ...

    def administrator_usage_summary(self) -> list[dict[str, Any]]: ...

    def administrator_policy_usage(self) -> list[dict[str, Any]]: ...


class LocalConversationStore:
    def __init__(self, path: Path):
        self.path = path
        initialise(path)

    def authorize_question(self, email: str, request_id: str) -> None:
        authorize_question(self.path, email, request_id)

    def save(self, email: str, question: str, answer: str, mode: str, source_ids: list[str], governance: GovernanceContext | None = None, request_id: str = "") -> int:
        question = validate_question(question)
        return save(
            self.path, email, question, answer, mode, source_ids,
            governance.answer_status if governance else "complete",
            governance.policy_area if governance else "",
            governance.recommended_owner if governance else "",
            request_id,
        )

    def history(self, email: str, limit: int = 20) -> list[tuple]:
        return history(self.path, email, limit)

    def export_history(self, email: str) -> list[tuple]:
        return history(self.path, email, 10_000)

    def set_feedback(self, conversation_id: str | int, email: str, value: str) -> None:
        set_feedback(self.path, int(conversation_id), email, value)

    def delete_my_history(self, email: str) -> int:
        return delete_history(self.path, email)

    def is_reviewer(self) -> bool:
        return False

    def reviewer_queue(self, limit: int = 100) -> list[dict[str, Any]]:
        return []

    def set_review_status(self, conversation_id: str | int, value: str) -> None:
        raise PermissionError("The local demonstration store has no cross-user reviewer queue.")

    def record_usage_event(self, event_type: str, idempotency_key: str = "", policy_area: str = "", answer_status: str = "", conversation_id: str | int | None = None) -> None:
        return None

    def is_administrator(self) -> bool:
        return False

    def administrator_usage_summary(self) -> list[dict[str, Any]]:
        return []

    def administrator_policy_usage(self) -> list[dict[str, Any]]:
        return []


class SupabaseConversationStore:
    """Cloud storage exposed only through identity-aware Supabase functions."""

    def __init__(self, client: Any, user_id: str, app_secret: str = ""):
        self.client = client
        self.user_id = user_id
        self.app_secret = app_secret

    def authorize_question(self, email: str, request_id: str) -> None:
        try:
            self.client.rpc(
                "pippa_authorize_question",
                {"p_request_id": request_id, "p_app_secret": self.app_secret},
            ).execute()
        except Exception as exc:
            message = str(exc)
            if "PIPPA_QUOTA_MINUTE" in message:
                raise QuestionQuotaError(
                    "You have reached 10 questions in one minute. Wait a moment and try again."
                ) from exc
            if "PIPPA_QUOTA_HOUR" in message:
                raise QuestionQuotaError(
                    "You have reached 60 questions in one hour. Try again later."
                ) from exc
            if "PIPPA_QUOTA_DAY" in message:
                raise QuestionQuotaError(
                    "You have reached today’s limit of 200 questions. Try again after the 24-hour window resets."
                ) from exc
            raise

    def save(self, email: str, question: str, answer: str, mode: str, source_ids: list[str], governance: GovernanceContext | None = None, request_id: str = "") -> str:
        question = validate_question(question)
        response = self.client.rpc(
            "pippa_save_conversation",
            {
                "p_question": question,
                "p_answer": answer,
                "p_mode": mode,
                "p_source_ids": source_ids,
                "p_answer_status": governance.answer_status if governance else "complete",
                "p_policy_area": governance.policy_area if governance else "",
                "p_recommended_owner": governance.recommended_owner if governance else "",
                "p_request_id": request_id,
                "p_app_secret": self.app_secret,
            },
        ).execute()
        conversation_id = response.data
        if isinstance(conversation_id, list):
            conversation_id = conversation_id[0] if conversation_id else None
        if isinstance(conversation_id, dict):
            conversation_id = conversation_id.get("id") or conversation_id.get("pippa_save_conversation")
        if not conversation_id:
            raise RuntimeError("Supabase did not return the saved conversation ID.")
        return str(conversation_id)

    def history(self, email: str, limit: int = 20) -> list[tuple]:
        response = self.client.rpc("pippa_my_history", {"p_limit": limit}).execute()
        return self._history_rows(response.data)

    def export_history(self, email: str) -> list[tuple]:
        response = self.client.rpc("pippa_export_my_history").execute()
        return self._history_rows(response.data)

    @staticmethod
    def _history_rows(data: Any) -> list[tuple]:
        return [
            (
                row["id"],
                row["created_at"],
                row["question"],
                row["answer"],
                row["mode"],
                ", ".join(row.get("source_ids") or []),
                row.get("feedback"),
            )
            for row in (data or [])
        ]

    def set_feedback(self, conversation_id: str | int, email: str, value: str) -> None:
        if value not in {"helpful", "needs_review"}:
            raise ValueError("Unsupported feedback value.")
        self.client.rpc(
            "pippa_set_my_feedback",
            {"p_conversation_id": str(conversation_id), "p_feedback": value},
        ).execute()

    def delete_my_history(self, email: str) -> int:
        response = self.client.rpc("pippa_delete_my_history").execute()
        deleted = response.data
        if isinstance(deleted, list):
            deleted = deleted[0] if deleted else 0
        if isinstance(deleted, dict):
            deleted = deleted.get("pippa_delete_my_history", 0)
        return int(deleted or 0)

    def is_reviewer(self) -> bool:
        response = (
            self.client.table("pippa_reviewers")
            .select("role")
            .eq("user_id", self.user_id)
            .limit(1)
            .execute()
        )
        return bool(response.data)

    def reviewer_queue(self, limit: int = 100) -> list[dict[str, Any]]:
        response = self.client.rpc("pippa_reviewer_queue", {"p_limit": limit}).execute()
        return list(response.data or [])

    def set_review_status(self, conversation_id: str | int, value: str) -> None:
        if value not in {"in_review", "resolved"}:
            raise ValueError("Unsupported review status.")
        self.client.rpc(
            "pippa_transition_review",
            {"p_conversation_id": str(conversation_id), "p_new_status": value},
        ).execute()

    def record_usage_event(self, event_type: str, idempotency_key: str = "", policy_area: str = "", answer_status: str = "", conversation_id: str | int | None = None) -> None:
        if event_type != "app_opened":
            raise ValueError("Unsupported usage event.")
        self.client.rpc(
            "pippa_record_app_open",
            {
                "p_idempotency_key": idempotency_key,
                "p_app_secret": self.app_secret,
            },
        ).execute()

    def is_administrator(self) -> bool:
        response = (
            self.client.table("pippa_reviewers")
            .select("role")
            .eq("user_id", self.user_id)
            .eq("role", "administrator")
            .limit(1)
            .execute()
        )
        return bool(response.data)

    def administrator_usage_summary(self) -> list[dict[str, Any]]:
        response = self.client.rpc("pippa_admin_usage_summary").execute()
        return list(response.data or [])

    def administrator_policy_usage(self) -> list[dict[str, Any]]:
        response = self.client.rpc("pippa_admin_policy_usage").execute()
        return list(response.data or [])

