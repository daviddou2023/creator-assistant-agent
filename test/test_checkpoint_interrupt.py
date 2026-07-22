"""Smoke test for LangGraph checkpointer + interrupt/resume Plan review.

Run:
    python test/test_checkpoint_interrupt.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from video_review_agent.graph import resume_video_review, run_video_review


def main() -> None:
    thread_id = "test-plan-review-thread"
    interrupted = run_video_review(
        video_id="demo-video-001",
        creator_id="checkpoint_test_creator",
        memory_enabled=False,
        require_plan_approval=True,
        thread_id=thread_id,
        use_llm=False,
    )

    interrupts = interrupted.get("__interrupt__", [])
    assert interrupts, "graph should interrupt and return a Plan payload"

    plan = interrupts[0].value
    assert plan["thread_id"] == thread_id
    assert plan["recommendations"], "Plan should include recommendations"

    revised_recommendations = [
        "用户确认后的建议：下一条视频优先拆解选题判断方法。",
        "用户确认后的建议：保留案例拆解结构，并放慢字幕节奏。",
    ]
    resumed = resume_video_review(
        thread_id=thread_id,
        resume_payload={
            "approved": True,
            "recommendations": revised_recommendations,
            "review_notes": "测试中模拟用户确认并修改 Plan。",
        },
    )

    assert "__interrupt__" not in resumed
    assert resumed["plan_approved"] is True
    assert resumed["recommendations"] == revised_recommendations
    assert revised_recommendations[0] in resumed["report"]
    assert resumed["report"]

    print("Checkpoint interrupt/resume smoke test passed.")
    print(f"Thread id: {thread_id}")
    print(f"Report length: {len(resumed['report'])}")


if __name__ == "__main__":
    main()
