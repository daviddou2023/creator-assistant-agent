"""Command line entry for the short-video review agent.

Run examples:
    python demo.py
    python demo.py --video-id demo-video-001 --days 7
    python demo.py --platform bilibili --video-id BV1xx411c7mD --days 30
    python demo.py --source data/sample_video_metrics.json --reports-dir reports
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path

from video_review_agent.graph import run_video_review


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a short-video traffic review report.")
    parser.add_argument("--video-id", default="demo-video-001", help="Video id to review.")
    parser.add_argument("--creator-id", default="default_creator", help="Creator id for memory retrieval.")
    parser.add_argument(
        "--platform",
        choices=["json", "bilibili"],
        default="json",
        help="Data source platform.",
    )
    parser.add_argument(
        "--source",
        default="data/sample_video_metrics.json",
        help="JSON data source path. Replace this with a platform collector later.",
    )
    parser.add_argument("--days", type=int, default=7, help="Days after publish to include.")
    parser.add_argument("--max-comments", type=int, default=50, help="Maximum comments to collect.")
    parser.add_argument(
        "--top-liked-comments",
        type=int,
        default=5,
        help="Number of top-liked Bilibili comments to record.",
    )
    parser.add_argument("--memory-dir", default="memory/qdrant", help="Local Qdrant memory directory.")
    parser.add_argument(
        "--disable-memory",
        action="store_true",
        help="Disable creator memory retrieval and storage for this run.",
    )
    parser.add_argument(
        "--reports-dir",
        default="reports",
        help="Directory used to store one folder per generated report.",
    )
    parser.add_argument(
        "--output",
        help="Optional exact markdown output path. If omitted, a timestamped report folder is created.",
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Use an LLM to polish the final report when API environment variables are configured.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    result = run_video_review(
        video_id=args.video_id,
        source_path=args.source,
        days_after_publish=args.days,
        platform=args.platform,
        max_comments=args.max_comments,
        top_liked_comments_limit=args.top_liked_comments,
        creator_id=args.creator_id,
        memory_dir=args.memory_dir,
        memory_enabled=not args.disable_memory,
        use_llm=args.use_llm,
    )

    report = result.get("report", "")
    output_path = resolve_output_path(
        video_id=args.video_id,
        reports_dir=args.reports_dir,
        output=args.output,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")

    print(f"Report written to: {output_path}")
    print("Open that markdown file to view the full report.")


def resolve_output_path(video_id: str, reports_dir: str, output: str | None = None) -> Path:
    if output:
        return Path(output)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_video_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", video_id).strip("-") or "video"
    report_dir = Path(reports_dir) / f"{safe_video_id}_{timestamp}"
    return report_dir / "report.md"


if __name__ == "__main__":
    main()
