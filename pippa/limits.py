from __future__ import annotations

import hashlib
import hmac
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator


MAX_QUESTION_CHARS = 4_000
QUESTION_LIMIT_PER_MINUTE = 10
QUESTION_LIMIT_PER_HOUR = 60
QUESTION_LIMIT_PER_DAY = 200
MAX_CONCURRENT_QUESTIONS = 10

AUTH_EMAIL_LIMIT_PER_HOUR = 300
AUTH_EMAIL_LIMIT_PER_ADDRESS_HOUR = 3
AUTH_EMAIL_LIMIT_PER_ADDRESS_DAY = 10
AUTH_EMAIL_RESEND_SECONDS = 60


class QuestionValidationError(ValueError):
    """A safe validation failure that can be shown to the person asking."""


class QuestionQuotaError(RuntimeError):
    """A safe quota failure returned by a controlled store operation."""


class QuestionCapacityError(RuntimeError):
    """Raised when all question-processing slots are already occupied."""


def validate_question(value: str) -> str:
    """Validate and normalize a question before retrieval or persistence."""
    question = str(value or "").strip()
    if not question:
        raise QuestionValidationError(
            "Enter a question or select one of the example scenarios before asking PIPPA."
        )
    if len(question) > MAX_QUESTION_CHARS:
        raise QuestionValidationError(
            f"Your question is {len(question):,} characters long. "
            f"Shorten it to {MAX_QUESTION_CHARS:,} characters or fewer and try again."
        )
    if "\x00" in question:
        raise QuestionValidationError("Remove unsupported control characters and try again.")
    return question


def sign_in_email_key(email: str, secret: str) -> str:
    """Return a non-reversible, deployment-specific key for sign-in quotas."""
    normalized_email = str(email or "").strip().lower()
    if len(secret) < 32:
        raise ValueError("The sign-in quota secret must contain at least 32 characters.")
    return hmac.new(
        secret.encode("utf-8"), normalized_email.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def new_request_id() -> str:
    return str(uuid.uuid4())


@dataclass
class QuestionCapacity:
    """Process-local admission control for expensive retrieval work."""

    maximum: int = MAX_CONCURRENT_QUESTIONS

    def __post_init__(self) -> None:
        if self.maximum < 1:
            raise ValueError("Question capacity must be at least one.")
        self._semaphore = threading.BoundedSemaphore(self.maximum)

    @contextmanager
    def slot(self, timeout_seconds: float = 10.0) -> Iterator[None]:
        acquired = self._semaphore.acquire(timeout=max(float(timeout_seconds), 0.0))
        if not acquired:
            raise QuestionCapacityError(
                "PIPPA is helping several people right now. Wait a moment and try again."
            )
        try:
            yield
        finally:
            self._semaphore.release()
