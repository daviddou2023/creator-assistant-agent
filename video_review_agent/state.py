"""Shared state schema for the LangGraph workflow."""

from __future__ import annotations

from typing import Any, TypedDict


class VideoReviewState(TypedDict, total=False):
    video_id: str
    source_path: str
    platform: str
    days_after_publish: int
    max_comments: int
    top_liked_comments_limit: int
    use_llm: bool

    raw_data: dict[str, Any]
    metrics_summary: dict[str, Any]
    comment_insights: dict[str, Any]
    content_insights: dict[str, Any]
    recommendations: list[str]
    report: str
    errors: list[str]
