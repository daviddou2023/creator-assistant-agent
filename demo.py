"""Run an evidence-driven video review from the command line."""

from __future__ import annotations

import argparse
from pathlib import Path

from video_review_agent.workflow import run_video_review


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review a short video using selected evidence.")
    parser.add_argument("--video-id", default="demo-video-001", help="Bilibili BV id or local sample video id.")
    parser.add_argument("--question", default="请复盘这条视频的表现", help="Question to investigate.")
    parser.add_argument("--creator-id", default="default_creator")
    parser.add_argument("--platform", choices=["json", "bilibili"], default="json")
    parser.add_argument("--source", default="data/sample_video_metrics.json")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--max-comments", type=int, default=50)
    parser.add_argument("--output", default="reports/review.md")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = run_video_review(
        video_id=args.video_id,
        user_question=args.question,
        platform=args.platform,
        source_path=args.source,
        creator_id=args.creator_id,
        days_after_publish=args.days,
        max_comments=args.max_comments,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result.get("report", ""), encoding="utf-8")
    print(f"Report written to: {output}")


if __name__ == "__main__":
    main()
