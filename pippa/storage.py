from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .limits import (
    QUESTION_LIMIT_PER_DAY,
    QUESTION_LIMIT_PER_HOUR,
    QUESTION_LIMIT_PER_MINUTE,
    QuestionQuotaError,
)


def initialise(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                created_at TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                mode TEXT NOT NULL,
                source_ids TEXT NOT NULL,
                feedback TEXT
            )
        """)
        existing_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(conversations)")
        }
        for column, declaration in (
            ("answer_status", "TEXT"),
            ("policy_area", "TEXT"),
            ("recommended_owner", "TEXT"),
            ("request_id", "TEXT"),
        ):
            if column not in existing_columns:
                connection.execute(f"ALTER TABLE conversations ADD COLUMN {column} {declaration}")
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS conversations_user_request_idx "
            "ON conversations (user_email, request_id) WHERE request_id IS NOT NULL"
        )
        connection.execute("""
            CREATE TABLE IF NOT EXISTS question_permits (
                user_email TEXT NOT NULL,
                request_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_email, request_id)
            )
        """)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        connection.execute("DELETE FROM conversations WHERE created_at < ?", (cutoff,))
        connection.execute(
            "DELETE FROM question_permits WHERE created_at < ?",
            ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),),
        )
        connection.commit()


def authorize_question(
    path: Path,
    email: str,
    request_id: str,
    now: datetime | None = None,
) -> None:
    timestamp = now or datetime.now(timezone.utc)
    with closing(sqlite3.connect(path)) as connection:
        existing = connection.execute(
            "SELECT 1 FROM question_permits WHERE user_email = ? AND request_id = ?",
            (email, request_id),
        ).fetchone()
        if existing:
            return
        counts: dict[str, int] = {}
        for name, delta in (
            ("minute", timedelta(minutes=1)),
            ("hour", timedelta(hours=1)),
            ("day", timedelta(days=1)),
        ):
            counts[name] = int(
                connection.execute(
                    "SELECT count(*) FROM question_permits WHERE user_email = ? AND created_at >= ?",
                    (email, (timestamp - delta).isoformat()),
                ).fetchone()[0]
            )
        if counts["minute"] >= QUESTION_LIMIT_PER_MINUTE:
            raise QuestionQuotaError("You have reached 10 questions in one minute. Wait a moment and try again.")
        if counts["hour"] >= QUESTION_LIMIT_PER_HOUR:
            raise QuestionQuotaError("You have reached 60 questions in one hour. Try again later.")
        if counts["day"] >= QUESTION_LIMIT_PER_DAY:
            raise QuestionQuotaError("You have reached today’s limit of 200 questions. Try again after the 24-hour window resets.")
        connection.execute(
            "INSERT INTO question_permits (user_email, request_id, created_at) VALUES (?, ?, ?)",
            (email, request_id, timestamp.isoformat()),
        )
        connection.commit()


def save(
    path: Path,
    email: str,
    question: str,
    answer: str,
    mode: str,
    source_ids: list[str],
    answer_status: str = "complete",
    policy_area: str = "",
    recommended_owner: str = "",
    request_id: str = "",
) -> int:
    with closing(sqlite3.connect(path)) as connection:
        if request_id:
            existing = connection.execute(
                "SELECT id FROM conversations WHERE user_email = ? AND request_id = ?",
                (email, request_id),
            ).fetchone()
            if existing:
                return int(existing[0])
        cursor = connection.execute(
            """INSERT INTO conversations
               (user_email, created_at, question, answer, mode, source_ids, answer_status, policy_area, recommended_owner, request_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                email,
                datetime.now(timezone.utc).isoformat(),
                question,
                answer,
                mode,
                ", ".join(source_ids),
                answer_status,
                policy_area,
                recommended_owner,
                request_id or None,
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)


def history(path: Path, email: str, limit: int = 20) -> list[tuple]:
    with closing(sqlite3.connect(path)) as connection:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        return connection.execute(
            "SELECT id, created_at, question, answer, mode, source_ids, feedback FROM conversations WHERE user_email = ? AND created_at >= ? ORDER BY id DESC LIMIT ?",
            (email, cutoff, limit),
        ).fetchall()


def delete_history(path: Path, email: str) -> int:
    with closing(sqlite3.connect(path)) as connection:
        cursor = connection.execute(
            "DELETE FROM conversations WHERE user_email = ?", (email,)
        )
        connection.commit()
        return int(cursor.rowcount)


def set_feedback(path: Path, conversation_id: int, email: str, value: str) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "UPDATE conversations SET feedback = ? WHERE id = ? AND user_email = ?",
            (value, conversation_id, email),
        )
        connection.commit()

