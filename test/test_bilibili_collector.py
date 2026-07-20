"""Manual smoke test for collecting public Bilibili video data.

Run:
    python test/test_bilibili_collector.py --bvid BV1xx411c7mD --days 30

Or set:
    $env:BILIBILI_TEST_BVID="BV..."
    python test/test_bilibili_collector.py
"""

from __future__ import annotations

import argparse
# 运行异步
import asyncio
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 导入bilibili异步抓取函数
from video_review_agent.bilibili_collector import collect_bilibili_video_data_async


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch public Bilibili video metrics and comments.")
    # 视频的BV号
    parser.add_argument("--bvid", default=os.getenv("BILIBILI_TEST_BVID", "BV1xx411c7mD"))
    # 抓取视频发布后多少天内的流量
    parser.add_argument("--days", type=int, default=30)
    # 抓取普通评论的最大数量
    parser.add_argument("--max-comments", type=int, default=10)
    # 抓取高赞评论的最大数量
    parser.add_argument("--top-liked-comments", type=int, default=5)
    # 抓取结果的本地JSON保存路径
    parser.add_argument("--output", default="test/output/bilibili_video_data.json")
    return parser


async def main() -> None:
    """
    主控异步函数：负责解析参数、调用抓取逻辑、保存数据并打印摘要信息
    """
    args = build_parser().parse_args()
    # 调用核心抓取函数。使用await来挂起并等待执行结果返回
    data = await collect_bilibili_video_data_async(
        video_id=args.bvid,
        days_after_publish=args.days,
        max_comments=args.max_comments,
        top_liked_comments_limit=args.top_liked_comments,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # 提取抓取数据中最后一次记录的指标快照数据
    latest = data["metric_snapshots"][-1]
    print(f"Fetched: {data['title']}")
    print(f"Views: {latest['views']}, Likes: {latest['likes']}, Shares: {latest['shares']}")
    print(f"Comments saved: {len(data['comments'])}")
    print(f"Top liked comments saved: {len(data.get('top_liked_comments', []))}")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
