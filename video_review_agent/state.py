"""Shared state schema for the LangGraph workflow."""

from __future__ import annotations

from typing import Any, TypedDict


class VideoReviewState(TypedDict, total=False):
    video_id: str
    user_question: str
    user_feedback: str
    creator_id: str
    source_path: str
    platform: str
    days_after_publish: int
    max_comments: int
    top_liked_comments_limit: int
    selected_hypotheses: list[dict[str, Any]]
    todos: list[dict[str, Any]]
    replan_attempts: int
    failed_tasks: list[str]
    observations: list[str]
    raw_data: dict[str, Any]
    selected_metrics: dict[str, Any]
    comments: list[dict[str, Any]]
    comment_insights: dict[str, Any]
    comment_counts: dict[str, Any]
    historical_experiences: list[dict[str, Any]]
    data_limitations: list[str]
    explanations: list[dict[str, Any]]
    hypotheses: list[dict[str, Any]]
    followup_validations: list[dict[str, Any]]
    evidence: list[str]
    summary: str
    report: str
