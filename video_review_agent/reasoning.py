"""Planning and evidence synthesis for the review workflow."""

from __future__ import annotations

import json
import re
from typing import Any

from video_review_agent.config import get_llm_config


def _ask_for_json(system: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    config = get_llm_config()
    if not config.enabled:
        return None
    try:
        from langchain.chat_models import init_chat_model

        model = init_chat_model(model=config.model, model_provider=config.provider)
        response = model.invoke(
            [
                ("system", system + " 只返回 JSON 对象，不要 Markdown。"),
                ("human", json.dumps(payload, ensure_ascii=False)),
            ]
        )
        text = str(response.content)
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception:
        return None


def create_plan(context: dict[str, Any]) -> list[dict[str, Any]]:
    result = _ask_for_json(
        "你负责规划短视频复盘任务。根据用户问题和可用数据，只选必要任务。"
        "任务 type 只能是 metrics、fetch_comments、clean_comments、analyze_comments、history；"
        "metrics keys 只能从可用指标中选择。返回 {\"todos\":[{\"id\":\"...\","
        "\"type\":\"metrics|fetch_comments|clean_comments|analyze_comments|history\","
        "\"keys\":[...],\"reason\":\"...\"}]}。评论任务只在问题需要评论信号时添加。",
        context,
    )
    available = set(context.get("available_metrics", []))
    todos = result.get("todos", []) if result else []
    normalized = []
    for index, todo in enumerate(todos):
        if not isinstance(todo, dict) or todo.get("type") not in {"metrics", "fetch_comments", "clean_comments", "analyze_comments", "history"}:
            continue
        item = dict(todo)
        item["id"] = str(item.get("id") or f"task-{index + 1}")
        item["keys"] = [key for key in item.get("keys", []) if key in available]
        if item.get("type") == "metrics" and any(key in item["keys"] for key in ("likes", "shares", "reply")) and "views" in available:
            item["keys"] = list(dict.fromkeys([*item["keys"], "views"]))
        item["status"] = "pending"
        normalized.append(item)
    if normalized:
        if any(item.get("type") in {"fetch_comments", "clean_comments", "analyze_comments"} for item in normalized):
            existing_types = {item.get("type") for item in normalized}
            for kind in ("fetch_comments", "clean_comments", "analyze_comments"):
                if kind not in existing_types:
                    normalized.append({"id": kind, "type": kind, "keys": [], "status": "pending"})
        if not any(item.get("type") == "history" for item in normalized):
            normalized.append({"id": "history", "type": "history", "keys": [], "status": "pending"})
        return normalized

    question = str(context.get("user_question", "")).lower()
    key_groups = {
        "views": ("播放", "流量", "曝光", "阅读", "播放量"),
        "likes": ("点赞", "喜欢", "高赞"),
        "shares": ("转发", "分享"),
        "favorites": ("收藏",),
        "coins": ("投币",),
        "reply": ("评论量", "回复量"),
    }
    selected = [key for key, terms in key_groups.items() if any(term in question for term in terms)]
    if any(key in selected for key in ("likes", "shares", "reply")) and "views" in available:
        selected = list(dict.fromkeys([*selected, "views"]))
    if not selected:
        selected = ["views", "likes", "shares", "reply"]
    selected = [key for key in selected if key in available]
    todos = [{"id": "metrics", "type": "metrics", "keys": selected, "status": "pending"}]
    if any(term in question for term in ("评论", "观众", "为什么", "原因", "反馈")):
        todos.extend([
            {"id": "fetch_comments", "type": "fetch_comments", "keys": [], "status": "pending"},
            {"id": "clean_comments", "type": "clean_comments", "keys": [], "status": "pending"},
            {"id": "analyze_comments", "type": "analyze_comments", "keys": [], "status": "pending"},
        ])
    todos.append({"id": "history", "type": "history", "keys": [], "status": "pending"})
    return todos


def explain_findings(context: dict[str, Any]) -> dict[str, Any] | None:
    return _ask_for_json(
        "你是证据驱动的视频复盘分析员。只根据输入证据解释信号；区分事实、推测和限制。"
        "证据不足时明确说无法判断；每条 evidence 必须逐字取自输入 evidence 数组。返回 {\"explanations\":[{\"claim\":\"...\","
        "\"evidence\":[\"输入 evidence 中原文\"],\"counter_evidence\":[\"反向证据或 limitation 中原文\"],\"confidence\":\"low|medium|high\","
        "\"limitations\":[\"...\"]}],\"hypotheses\":[{\"statement\":\"...\","
        "\"scope\":\"...\",\"confidence\":\"low|medium|high\","
        "\"validation\":\"下条视频可观察的指标和判定方式\"}],\"summary\":\"...\"}。"
        "如果提供了 selected_hypotheses，再返回 followup_validations 数组，元素包含 hypothesis_id、"
        "status（supported|weakened|inconclusive）、evidence。不能声称相关性证明因果。",
        context,
    )
