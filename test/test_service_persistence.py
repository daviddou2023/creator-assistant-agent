"""Smoke test for SQLite job persistence and SSE event replay.

Run:
    python test/test_service_persistence.py
"""

from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from video_review_agent.event_cache import InMemorySSEEventCache
from video_review_agent.job_store import SQLiteJobStore
from video_review_agent.service import create_app


def wait_for_status(client, job_id: str, expected: set[str], timeout: float = 25.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/api/reviews/{job_id}")
        assert response.status_code == 200
        payload = response.get_json()
        if payload["status"] in expected:
            return payload
        time.sleep(0.5)
    raise AssertionError(f"job {job_id} did not reach {expected}")


def main() -> None:
    output_dir = PROJECT_ROOT / "test" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    db_path = output_dir / f"service_persistence_{uuid.uuid4().hex}.sqlite3"
    store = SQLiteJobStore(db_path)
    cache = InMemorySSEEventCache()

    first_app = create_app(job_store=store, event_cache=cache)
    first_client = first_app.test_client()
    start = first_client.post(
        "/api/reviews",
        json={
            "video_url": "demo-video-001",
            "creator_id": "persistence_test_creator",
            "platform": "json",
            "days_after_publish": 7,
            "max_comments": 5,
            "memory_enabled": False,
            "require_plan_approval": True,
            "use_llm": False,
        },
    )
    assert start.status_code == 202
    job_id = start.get_json()["job_id"]

    interrupted = wait_for_status(first_client, job_id, {"awaiting_approval"})
    assert interrupted["plan"]["status"] == "awaiting_user_approval"

    second_app = create_app(job_store=store, event_cache=cache)
    second_client = second_app.test_client()
    hydrated = second_client.get(f"/api/reviews/{job_id}")
    assert hydrated.status_code == 200
    hydrated_payload = hydrated.get_json()
    assert hydrated_payload["status"] == "awaiting_approval"
    assert hydrated_payload["plan"]["video_id"] == "demo-video-001"
    assert hydrated_payload["last_event"]["type"] == "interrupted"

    with second_client.get(f"/api/reviews/{job_id}/events", buffered=False) as stream:
        chunks = []
        for raw_chunk in stream.response:
            chunk = raw_chunk.decode("utf-8") if isinstance(raw_chunk, bytes) else raw_chunk
            chunks.append(chunk)
            if "interrupted" in chunk:
                break
        assert any("node_update" in chunk for chunk in chunks)
        assert any("interrupted" in chunk for chunk in chunks)

    resume = second_client.post(
        f"/api/reviews/{job_id}/resume",
        json={"resume_payload": {"approved": True, "review_notes": "persisted resume"}},
    )
    assert resume.status_code == 202

    completed = wait_for_status(second_client, job_id, {"completed"})
    assert completed["result"]["report"]

    third_app = create_app(job_store=store, event_cache=cache)
    third_client = third_app.test_client()
    persisted = third_client.get(f"/api/reviews/{job_id}").get_json()
    assert persisted["status"] == "completed"
    assert persisted["result"]["report"]

    print("Service persistence smoke test passed.")
    print(f"Job id: {job_id}")
    print(f"SQLite db: {db_path}")
    print(f"Final status: {persisted['status']}")


if __name__ == "__main__":
    main()
