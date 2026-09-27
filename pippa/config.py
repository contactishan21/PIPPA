from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
KNOWLEDGE_DIR = APP_DIR / "knowledge" / "active_documents"
DB_PATH = APP_DIR / "pippa_history.db"


@dataclass(frozen=True)
class Settings:
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "").strip()
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-5-mini").strip()
    top_k: int = 5
    minimum_score: float = 2.0

    @property
    def ai_enabled(self) -> bool:
        return bool(self.openai_api_key)
