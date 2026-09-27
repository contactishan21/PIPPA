from __future__ import annotations

import json
import statistics
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pippa.answering import answer_question
from pippa.config import Settings
from pippa.knowledge import KnowledgeBase
from pippa.limits import QuestionCapacity


LEVELS = (10, 25, 50, 100)
QUESTION = "Who approves a financial commitment of AED 60,000?"


def run_level(users: int, kb: KnowledgeBase, settings: Settings) -> dict:
    gate = QuestionCapacity(maximum=10)
    start_together = threading.Barrier(users)

    def ask() -> float:
        # Release all workers together; submitting futures alone is not proof
        # of overlapping demand when individual answers are very fast.
        start_together.wait(timeout=30)
        started = time.perf_counter()
        with gate.slot(timeout_seconds=10):
            answer = answer_question(QUESTION, kb, settings)
            if answer.status != "complete" or "VP/COO plus Finance Controller" not in answer.body:
                raise AssertionError("Concurrent answer changed its controlled conclusion.")
        return time.perf_counter() - started

    latencies: list[float] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=users) as executor:
        futures = [executor.submit(ask) for _ in range(users)]
        for future in as_completed(futures):
            try:
                latencies.append(future.result())
            except Exception as exc:
                errors.append(type(exc).__name__)

    ordered = sorted(latencies)
    p95_index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95) - 1)) if ordered else 0
    return {
        "simulated_users": users,
        "completed": len(latencies),
        "errors": errors,
        "p50_seconds": round(statistics.median(ordered), 4) if ordered else None,
        "p95_seconds": round(ordered[p95_index], 4) if ordered else None,
    }


def main() -> int:
    kb = KnowledgeBase(ROOT / "knowledge" / "active_documents")
    settings = Settings(openai_api_key="", top_k=5, minimum_score=2.0)
    report = [run_level(level, kb, settings) for level in LEVELS]
    output = ROOT / "outputs" / "PIPPA_phase3_local_load.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    passed = all(not row["errors"] and row["completed"] == row["simulated_users"] and row["p95_seconds"] < 3 for row in report)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
