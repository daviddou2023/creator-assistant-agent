"""Small, explicit tools available to the planning workflow."""

from __future__ import annotations

from typing import Any


AVAILABLE_PUBLIC_METRICS = ("views", "likes", "shares", "favorites", "coins", "danmaku", "reply")
UNAVAILABLE_PRIVATE_METRICS = ("five_second_bounce_rate", "average_watch_duration", "completion_rate", "retention_curve")


def get_metrics_by_keys(raw_data: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    snapshots = raw_data.get("metric_snapshots", [])
    if not snapshots:
        return {"values": {}, "unavailable": list(keys)}
    ordered = sorted(snapshots, key=lambda item: item.get("captured_at", ""))
    first = ordered[0]
    latest = ordered[-1]
    values = {key: latest[key] for key in keys if key in latest}
    growth = {
        key: values[key] - first[key]
        for key in values
        if key in first and isinstance(values[key], (int, float)) and isinstance(first[key], (int, float))
    } if len(ordered) > 1 else {}
    views = values.get("views")
    derived = {}
    if isinstance(views, (int, float)) and views > 0:
        if isinstance(values.get("likes"), (int, float)):
            derived["like_rate"] = round(values["likes"] / views, 4)
        if isinstance(values.get("shares"), (int, float)):
            derived["share_rate"] = round(values["shares"] / views, 4)
        interactions = [values[key] for key in ("likes", "shares", "reply") if isinstance(values.get(key), (int, float))]
        if interactions:
            derived["engagement_rate"] = round(sum(interactions) / views, 4)
    return {
        "values": values,
        "growth": growth,
        "snapshots_count": len(ordered),
        "derived": derived,
        "unavailable": [key for key in keys if key not in values],
    }


def clean_comments(comments: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    clean = []
    seen = set()
    removed_empty = removed_duplicate = 0
    for comment in comments:
        text = " ".join(str(comment.get("text", "")).split())
        if not text:
            removed_empty += 1
            continue
        normalized = text.casefold()
        if normalized in seen:
            removed_duplicate += 1
            continue
        seen.add(normalized)
        clean.append({**comment, "text": text})
    return clean, {"removed_empty": removed_empty, "removed_duplicate": removed_duplicate}
