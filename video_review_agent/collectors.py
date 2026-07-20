"""Data collectors for platform metrics and comments."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from video_review_agent.bilibili_collector import collect_bilibili_video_data


def load_json_source(source_path: str) -> dict[str, Any]:
    path = Path(source_path)
    if not path.exists():
        raise FileNotFoundError(f"Data source not found: {source_path}")
    return json.loads(path.read_text(encoding="utf-8"))


def collect_video_data(
    video_id: str,
    source_path: str,
    days_after_publish: int,
    platform: str = "json",
    max_comments: int = 50,
    top_liked_comments_limit: int = 5,
) -> dict[str, Any]:
    """
    核心入口函数：从 JSON 模拟数据源或真实的线上平台采集单条视频的记录。
    
    参数:
        video_id: 视频的唯一标识符（如 BV号）。
        source_path: JSON 模拟数据文件的本地路径（当 platform="json" 时使用）。
        days_after_publish: 时间窗口限制，只采集视频发布后几天内的数据。
        platform: 平台名称，支持 "json" (本地测试) 或 "bilibili" (真实接口)。
        max_comments: 采集普通评论的最大条数。
        top_liked_comments_limit: 采集高赞评论的最大条数。
    """

    if platform == "bilibili":
        return collect_bilibili_video_data(
            video_id=video_id,
            days_after_publish=days_after_publish,
            max_comments=max_comments,
            top_liked_comments_limit=top_liked_comments_limit,
        )

    if platform != "json":
        raise ValueError(f"Unsupported platform: {platform}")

    payload = load_json_source(source_path)
    videos = payload.get("videos", [])
    video = next((item for item in videos if item.get("video_id") == video_id), None)
    if not video:
        raise ValueError(f"Video id not found in source: {video_id}")

    publish_time = _parse_datetime(video["published_at"])
    cutoff = publish_time + timedelta(days=days_after_publish)

    snapshots = [
        item
        for item in video.get("metric_snapshots", [])
        if publish_time <= _parse_datetime(item["captured_at"]) <= cutoff
    ]
    comments = [
        item
        for item in video.get("comments", [])
        if publish_time <= _parse_datetime(item["created_at"]) <= cutoff
    ]

    return {**video, "metric_snapshots": snapshots, "comments": comments}


def _parse_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
