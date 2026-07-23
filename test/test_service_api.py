"""Smoke test for the Flask review service and SSE-friendly job lifecycle.

Run:
    python test/test_service_api.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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
    app = create_app()
    client = app.test_client()

    start = client.post(
        "/api/reviews",
        json={
            "video_url": "demo-video-001",
            "creator_id": "service_test_creator",
            "platform": "json",
            "days_after_publish": 7,
            "max_comments": 5,
            "top_liked_comments_limit": 5,
            "memory_enabled": False,
            "require_plan_approval": True,
            "use_llm": False,
        },
    )
    assert start.status_code == 202
    start_payload = start.get_json()
    job_id = start_payload["job_id"]

    interrupted = wait_for_status(client, job_id, {"awaiting_approval"})
    assert interrupted["plan"], "plan should be available while waiting for approval"

    with client.get(f"/api/reviews/{job_id}/events", buffered=False) as stream:
        chunks = []
        for raw_chunk in stream.response:
            chunk = raw_chunk.decode("utf-8") if isinstance(raw_chunk, bytes) else raw_chunk
            chunks.append(chunk)
            if "interrupted" in chunk:
                break
        assert any("node_update" in chunk for chunk in chunks)
        assert any("interrupted" in chunk for chunk in chunks)

    resume = client.post(
        f"/api/reviews/{job_id}/resume",
        json={
            "resume_payload": {
                "approved": True,
                "recommendations": [
                    "测试中确认 Plan 继续执行。",
                    "测试中修改了建议文本。",
                ],
                "review_notes": "service test resume",
            }
        },
    )
    assert resume.status_code == 202

    completed = wait_for_status(client, job_id, {"completed"})
    result = completed["result"]
    assert result["report"]
    assert result["dashboard_data"]["retention_curve"]
    assert result["dashboard_data"]["cards"]["views"] > 0

    dashboard = client.get("/")
    assert dashboard.status_code == 200

    print("Service API smoke test passed.")
    print(f"Job id: {job_id}")
    print(f"Status: {completed['status']}")
    print(f"Retention points: {len(result['dashboard_data']['retention_curve'])}")
    print(f"Report length: {len(result['report'])}")


if __name__ == "__main__":
    main()
