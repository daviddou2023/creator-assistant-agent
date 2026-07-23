"""Dashboard-oriented numeric payloads for charts and cards."""

from __future__ import annotations

from typing import Any


def build_dashboard_data(
    raw_data: dict[str, Any],
    metrics_summary: dict[str, Any],
    comment_insights: dict[str, Any],
) -> dict[str, Any]:
    snapshots = sorted(raw_data.get("metric_snapshots", []), key=lambda item: item["captured_at"])
    max_views = max([int(item.get("views", 0)) for item in snapshots] or [0])

    trend_points = []
    for item in snapshots:
        views = int(item.get("views", 0))
        likes = int(item.get("likes", 0))
        shares = int(item.get("shares", 0))
        engagement_rate = _ratio(likes + shares, views)
        trend_points.append(
            {
                "label": item.get("captured_at", ""),
                "views": views,
                "likes": likes,
                "shares": shares,
                "engagement_rate": engagement_rate,
                "retention_index": _ratio(views, max_views),
            }
        )

    sentiment = comment_insights.get("sentiment", {})
    return {
        "cards": {
            "views": int(metrics_summary.get("views", 0)),
            "likes": int(metrics_summary.get("likes", 0)),
            "shares": int(metrics_summary.get("shares", 0)),
            "comments": int(metrics_summary.get("comments", 0)),
            "like_rate": float(metrics_summary.get("like_rate", 0)),
            "share_rate": float(metrics_summary.get("share_rate", 0)),
            "comment_rate": float(metrics_summary.get("comment_rate", 0)),
        },
        "growth": metrics_summary.get("growth", {}),
        "trend_points": trend_points,
        "retention_curve": [
            {
                "label": item["label"],
                "value": item["retention_index"],
            }
            for item in trend_points
        ],
        "engagement_curve": [
            {
                "label": item["label"],
                "value": item["engagement_rate"],
            }
            for item in trend_points
        ],
        "sentiment": {
            "positive": int(sentiment.get("positive", 0)),
            "neutral": int(sentiment.get("neutral", 0)),
            "negative": int(sentiment.get("negative", 0)),
        },
        "top_keywords": [
            {"keyword": keyword, "count": count}
            for keyword, count in comment_insights.get("hot_keywords", [])[:10]
        ],
    }


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0
    return round(numerator / denominator, 4)
