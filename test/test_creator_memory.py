"""Smoke test for creator preference memory with local Chroma storage.

Run:
    python test/test_creator_memory.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from video_review_agent.graph import run_video_review
from video_review_agent.memory import CreatorMemoryStore


def main() -> None:
    memory_dir = PROJECT_ROOT / "test" / "output" / "creator_memory_qdrant"
    if memory_dir.exists():
        shutil.rmtree(memory_dir)

    creator_id = "test_creator_memory"
    first = run_video_review(
        video_id="demo-video-001",
        creator_id=creator_id,
        memory_dir=str(memory_dir),
        memory_enabled=True,
        use_llm=False,
    )
    assert first.get("stored_experience_id"), "first run should store one experience"
    assert first.get("historical_preferences") == [], "first run should not retrieve prior memories"

    store = CreatorMemoryStore(persist_dir=str(memory_dir))
    stored = store.search_creator_preferences(
        creator_id=creator_id,
        query="账号定位 开头钩子 案例拆解 选题密度",
        limit=3,
    )
    store.close()
    assert stored, "stored creator memory should be queryable"
    assert stored[0]["metadata"]["creator_id"] == creator_id

    second = run_video_review(
        video_id="demo-video-001",
        creator_id=creator_id,
        memory_dir=str(memory_dir),
        memory_enabled=True,
        use_llm=False,
    )
    memories = second.get("historical_preferences", [])
    assert memories, "second run should retrieve creator historical preferences"
    assert "历史偏好参考" in second.get("report", "")

    print("Creator memory smoke test passed.")
    print(f"Stored id: {first['stored_experience_id']}")
    print(f"Retrieved memories: {len(memories)}")
    print(f"Memory dir: {memory_dir}")


if __name__ == "__main__":
    main()
