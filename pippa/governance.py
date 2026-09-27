"""Private governance metadata derived from an already-classified answer.

This module never changes retrieval or a guardrail decision.  It records the
decision PIPPA has already made so an authorised reviewer can identify content
gaps without reinterpreting an employee's question.
"""

from __future__ import annotations

from dataclasses import dataclass
import csv
import io

from .answering import Answer
from .knowledge import KnowledgeBase


@dataclass(frozen=True)
class GovernanceContext:
    answer_status: str
    policy_area: str
    recommended_owner: str


def context_for(answer: Answer, kb: KnowledgeBase) -> GovernanceContext:
    """Return safe reviewer-routing metadata for a completed answer."""
    policy_area = "Unmatched policy area"
    if answer.hits:
        document = kb.document_for(answer.hits[0].passage.document_id)
        if document and document.function:
            policy_area = document.function
    return GovernanceContext(
        answer_status=answer.status,
        policy_area=policy_area,
        recommended_owner=answer.escalation_contact,
    )


def personal_metrics(rows: list[tuple]) -> dict[str, int]:
    """Summarise one user's own history without exposing other users' data."""
    modes = [str(row[4]) for row in rows]
    feedback = [str(row[6] or "") for row in rows]
    return {
        "questions": len(rows),
        "evidence_complete": sum(mode == "Evidence complete" for mode in modes),
        "needs_attention": sum(mode != "Evidence complete" for mode in modes),
        "flagged_for_review": sum(value == "needs_review" for value in feedback),
    }


def history_csv(rows: list[tuple]) -> str:
    """Export only the signed-in user's already-authorized history rows."""
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["created_at_utc", "question", "answer", "mode", "source_ids", "feedback"])
    for row in rows:
        writer.writerow([row[1], row[2], row[3], row[4], row[5], row[6] or ""])
    return output.getvalue()

