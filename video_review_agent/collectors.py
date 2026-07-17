"""Data collectors for platform metrics and comments."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def load_json_source(source_path: str) -> dict[str, Any]:
    path = Path(source_path)
    if not path.exists():
        raise FileNotFoundError(f"Data source not found: {source_path}")
    return json.loads(path.read_text(encoding="utf-8"))


def collect_video_data(video_id: str, source_path: str, days_after_publish: int) -> dict[str, Any]:
    """Load one video record and keep snapshots/comments in the requested time window."""

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
