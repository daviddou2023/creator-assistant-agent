"""Smoke test for the in-process review API."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from video_review_agent.service import create_app


def wait_for_status(client, job_id: str, timeout: float = 25.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/api/reviews/{job_id}")
        assert response.status_code == 200
        payload = response.get_json()
        if payload["status"] in {"completed", "failed"}:
            return payload
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} did not finish")


def main() -> None:
    with TemporaryDirectory() as directory:
        os.environ["VIDEO_REVIEW_EXPERIENCE_PATH"] = str(Path(directory) / "experiences.json")
        client = create_app().test_client()
        start = client.post("/api/reviews", json={
            "video_id": "demo-video-001",
            "user_question": "播放量和点赞量表现如何？",
            "creator_id": "service_test_creator",
            "platform": "json",
        })
        assert start.status_code == 202
        job_id = start.get_json()["job_id"]
        completed = wait_for_status(client, job_id)
        assert completed["status"] == "completed"
        result = completed["result"]
        assert result["report"]
        assert result["selected_metrics"]["values"]["views"] > 0
        assert client.get("/").status_code == 200

        saved = client.post(f"/api/reviews/{job_id}/feedback", json={"satisfied": True})
        assert saved.status_code == 200
        assert client.get("/api/hypotheses?creator_id=service_test_creator").status_code == 200

        events = client.get(f"/api/reviews/{job_id}/events").get_data(as_text=True)
        assert "node_update" in events
        assert "completed" in events
        print("In-process review API smoke test passed.")


if __name__ == "__main__":
    main()
