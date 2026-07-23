"""Shared state schema for the LangGraph workflow."""

from __future__ import annotations

from typing import Any, TypedDict


class VideoReviewState(TypedDict, total=False):
    video_id: str
    creator_id: str
    source_path: str
    platform: str
    days_after_publish: int
    max_comments: int
    top_liked_comments_limit: int
    memory_dir: str
    memory_enabled: bool
    use_llm: bool
    require_plan_approval: bool
    checkpoint_thread_id: str

    historical_preferences: list[dict[str, Any]]
    raw_data: dict[str, Any]
    metrics_summary: dict[str, Any]
    comment_insights: dict[str, Any]
    dashboard_data: dict[str, Any]
    content_insights: dict[str, Any]
    recommendations: list[str]
    execution_plan: dict[str, Any]
    plan_approved: bool
    plan_review_notes: str
    stored_experience_id: str
    report: str
    errors: list[str]
