"""Bounded plan, execute, verify workflow for evidence-driven video reviews."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from video_review_agent.analytics import analyze_comments
from video_review_agent.collectors import collect_video_data
from video_review_agent.experience_store import ExperienceStore
from video_review_agent.reasoning import create_plan, explain_findings
from video_review_agent.state import VideoReviewState
from video_review_agent.tools import (
    AVAILABLE_PUBLIC_METRICS,
    UNAVAILABLE_PRIVATE_METRICS,
    clean_comments,
    get_metrics_by_keys,
)


def build_graph():
    graph = StateGraph(VideoReviewState)
    graph.add_node("plan", plan_node)
    graph.add_node("execute", execute_node)
    graph.add_node("replan", replan_node)
    graph.add_node("verify", verify_node)
    graph.add_node("report", report_node)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "execute")
    graph.add_conditional_edges("execute", route_after_execute, {"replan": "replan", "verify": "verify"})
    graph.add_edge("replan", "execute")
    graph.add_edge("verify", "report")
    graph.add_edge("report", END)
    return graph.compile()


def run_video_review(
    video_id: str,
    user_question: str = "请复盘这条视频的表现",
    platform: str = "bilibili",
    source_path: str = "data/sample_video_metrics.json",
    creator_id: str = "default_creator",
    days_after_publish: int = 7,
    max_comments: int = 50,
    top_liked_comments_limit: int = 5,
    selected_hypotheses: list[dict[str, Any]] | None = None,
    user_feedback: str = "",
) -> VideoReviewState:
    return build_graph().invoke({
        "video_id": video_id,
        "user_question": user_question,
        "platform": platform,
        "source_path": source_path,
        "creator_id": creator_id,
        "days_after_publish": days_after_publish,
        "max_comments": max_comments,
        "top_liked_comments_limit": top_liked_comments_limit,
        "selected_hypotheses": selected_hypotheses or [],
        "user_feedback": user_feedback,
        "observations": [user_feedback] if user_feedback else [],
        "replan_attempts": 0,
    })


def plan_node(state: VideoReviewState) -> VideoReviewState:
    requested_unavailable = _requested_private_metrics(state.get("user_question", ""))
    history = ExperienceStore().search(
        state.get("creator_id", "default_creator"),
        state.get("user_question", ""),
    )
    context = {
        "user_question": state.get("user_question", "请复盘这条视频的表现"),
        "video_id": state.get("video_id", ""),
        "platform": state.get("platform", "bilibili"),
        "available_metrics": list(AVAILABLE_PUBLIC_METRICS),
        "unavailable_metrics": list(UNAVAILABLE_PRIVATE_METRICS),
        "selected_hypotheses": state.get("selected_hypotheses", []),
        "historical_experiences": history,
        "requested_unavailable_metrics": requested_unavailable,
        "observations": state.get("observations", []),
        "user_feedback": state.get("user_feedback", ""),
        "replan_attempts": state.get("replan_attempts", 0),
    }
    return {
        "todos": create_plan(context),
        "observations": context["observations"],
        "historical_experiences": history,
        "requested_unavailable_metrics": requested_unavailable,
    }


def execute_node(state: VideoReviewState) -> VideoReviewState:
    todos = [dict(item) for item in state.get("todos", [])]
    metric_keys = list(dict.fromkeys(key for item in todos if item.get("type") == "metrics" for key in item.get("keys", [])))
    wants_comments = any(item.get("type") == "fetch_comments" for item in todos)
    observations = list(state.get("observations", []))
    failed = []
    raw_data: dict[str, Any] = {}
    selected_metrics: dict[str, Any] = {"values": {}, "unavailable": []}
    comments: list[dict[str, Any]] = []
    comment_insights: dict[str, Any] = {}
    comment_counts: dict[str, Any] = {
        "requested": wants_comments,
        "platform_total": None,
        "fetched": 0,
        "effective": 0,
        "sample_limit": state.get("max_comments", 50),
    }
    history = list(state.get("historical_experiences", []))

    try:
        raw_data = collect_video_data(
            video_id=state.get("video_id", ""),
            source_path=state.get("source_path", "data/sample_video_metrics.json"),
            days_after_publish=state.get("days_after_publish", 7),
            platform=state.get("platform", "bilibili"),
            max_comments=state.get("max_comments", 50),
            top_liked_comments_limit=state.get("top_liked_comments_limit", 5),
            include_comments=wants_comments,
        )
        selected_metrics = get_metrics_by_keys(raw_data, metric_keys)
        comment_counts.update(raw_data.get("comment_collection", {}))
        comment_counts["fetched"] = int(comment_counts.get("fetched_count", 0))
        for error in raw_data.get("collection_errors", []):
            observations.append(error)
    except Exception as exc:
        failed = [item.get("id", "collect") for item in todos if item.get("type") in {"metrics", "fetch_comments"}]
        observations.append(f"采集失败：{type(exc).__name__}: {exc}")

    for item in todos:
        kind = item.get("type")
        if kind == "history":
            item["status"] = "completed"
        elif kind == "fetch_comments":
            comment_error = any(error.startswith("comments:") for error in raw_data.get("collection_errors", []))
            item["status"] = "failed" if comment_error or not raw_data else "completed"
            if comment_error:
                failed.append(item.get("id", "fetch_comments"))
        elif kind == "metrics":
            item["status"] = "completed" if raw_data else "failed"

    for item in todos:
        if item.get("type") == "clean_comments":
            comments, cleaning = clean_comments(raw_data.get("comments", []))
            comment_counts["effective"] = len(comments)
            comment_counts["removed_empty"] = cleaning["removed_empty"]
            comment_counts["removed_duplicate"] = cleaning["removed_duplicate"]
            item["status"] = "completed" if comments else "empty"
            item["cleaning"] = cleaning
            if not comments and wants_comments:
                observations.append("评论清洗后没有可分析的评论样本。")
                failed.append(item.get("id", "clean_comments"))
    for item in todos:
        if item.get("type") == "analyze_comments":
            comment_insights = analyze_comments({"comments": comments})
            item["status"] = "completed" if comments else "skipped"

    selected_metrics["unavailable"] = list(dict.fromkeys([
        *selected_metrics.get("unavailable", []),
        *state.get("requested_unavailable_metrics", []),
    ]))
    return {
        "raw_data": raw_data,
        "selected_metrics": selected_metrics,
        "comments": comments,
        "comment_insights": comment_insights,
        "comment_counts": comment_counts,
        "historical_experiences": history,
        "todos": todos,
        "failed_tasks": failed,
        "observations": observations,
        "data_limitations": _data_limitations(raw_data, selected_metrics, wants_comments),
    }


def route_after_execute(state: VideoReviewState) -> str:
    attempts = state.get("replan_attempts", 0)
    return "replan" if state.get("failed_tasks") and attempts < 2 else "verify"


def replan_node(state: VideoReviewState) -> VideoReviewState:
    attempts = state.get("replan_attempts", 0) + 1
    removed = set(state.get("failed_tasks", []))
    context = {
        "user_question": state.get("user_question", ""),
        "video_id": state.get("video_id", ""),
        "platform": state.get("platform", "bilibili"),
        "available_metrics": list(AVAILABLE_PUBLIC_METRICS),
        "unavailable_metrics": list(UNAVAILABLE_PRIVATE_METRICS),
        "observations": state.get("observations", []),
        "failed_tasks": list(removed),
        "replan_attempts": attempts,
    }
    replacement = create_plan(context)
    failed_comments = any(
        item.get("type") in {"fetch_comments", "clean_comments", "analyze_comments"} and item.get("id") in removed
        for item in state.get("todos", [])
    )
    if failed_comments:
        replacement = [item for item in replacement if item.get("type") not in {"fetch_comments", "clean_comments", "analyze_comments"}]
    previous = [item for item in state.get("todos", []) if item.get("id") not in removed]
    seen = {(item.get("type"), tuple(item.get("keys", []))) for item in previous}
    replacement = [
        item for item in replacement
        if (item.get("type"), tuple(item.get("keys", []))) not in seen
    ]
    if attempts >= 2:
        replacement = [item for item in replacement if item.get("type") not in {"fetch_comments", "clean_comments", "analyze_comments"}]
    return {"todos": previous + replacement, "replan_attempts": attempts, "failed_tasks": []}


def verify_node(state: VideoReviewState) -> VideoReviewState:
    metrics = state.get("selected_metrics", {}).get("values", {})
    comments = state.get("comment_insights", {})
    evidence = [f"{key}: {value}" for key, value in metrics.items()]
    evidence.extend(
        f"{key} 增量: {value}"
        for key, value in state.get("selected_metrics", {}).get("growth", {}).items()
    )
    evidence.extend(
        f"{key}: {value:.2%}（按已取指标计算）"
        for key, value in state.get("selected_metrics", {}).get("derived", {}).items()
    )
    if comments:
        evidence.extend([
            f"有效评论样本数: {comments.get('total', 0)}",
            f"评论高频词: {comments.get('hot_keywords', [])}",
        ])
        evidence.extend(f"代表性评论: {text}" for text in comments.get("representative_comments", [])[:5])
    context = {
        "user_question": state.get("user_question", ""),
        "video": {key: state.get("raw_data", {}).get(key) for key in ("video_id", "title", "description", "published_at")},
        "metrics": metrics,
        "metric_growth": state.get("selected_metrics", {}).get("growth", {}),
        "comments": comments,
        "comment_counts": state.get("comment_counts", {}),
        "historical_experiences": state.get("historical_experiences", []),
        "selected_hypotheses": state.get("selected_hypotheses", []),
        "user_feedback": state.get("user_feedback", ""),
        "limitations": state.get("data_limitations", []),
        "evidence": evidence,
    }
    result = explain_findings(context) or _fallback_explanation(context)
    result = _validate_findings(
        result,
        evidence,
        state.get("selected_hypotheses", []),
        state.get("data_limitations", []),
    )
    return {
        "explanations": result.get("explanations", []),
        "hypotheses": result.get("hypotheses", []),
        "followup_validations": result.get("followup_validations", []),
        "evidence": evidence,
        "summary": result.get("summary", ""),
    }


def report_node(state: VideoReviewState) -> VideoReviewState:
    metrics = state.get("selected_metrics", {}).get("values", {})
    lines = [
        f"# 视频复盘：{state.get('raw_data', {}).get('title') or state.get('video_id', '')}",
        "",
        f"**问题：** {state.get('user_question', '请复盘这条视频的表现')}",
        "",
        "## 执行计划",
    ]
    lines.extend(f"- [{item.get('status', 'pending')}] {item.get('reason') or item.get('type')}: {', '.join(item.get('keys', []))}" for item in state.get("todos", []))
    lines.extend(["", "## 已取指标"])
    lines.extend(f"- {key}: {value}" for key, value in metrics.items())
    lines.extend(f"- {key} 增量: {value}" for key, value in state.get("selected_metrics", {}).get("growth", {}).items())
    lines.extend(
        f"- {key}: {value:.2%}（由已取指标计算）"
        for key, value in state.get("selected_metrics", {}).get("derived", {}).items()
    )
    if not metrics:
        lines.append("- 没有取得可用指标。")
    comment_counts = state.get("comment_counts", {})
    lines.extend(["", "## 评论采样口径"])
    if comment_counts.get("requested"):
        lines.extend([
            f"- 平台评论总数：{comment_counts.get('platform_total', '未知')}",
            f"- 本次抓取：{comment_counts.get('fetched', 0)} 条（上限 {comment_counts.get('sample_limit', '未知')}）",
            f"- 清洗后有效样本：{comment_counts.get('effective', 0)} 条",
            f"- 清洗移除：空评论 {comment_counts.get('removed_empty', 0)} 条，重复评论 {comment_counts.get('removed_duplicate', 0)} 条",
        ])
    else:
        lines.append("- 本次分析计划未要求抓取评论。")
    lines.extend(["", "## 解释与证据"])
    for item in state.get("explanations", []):
        lines.extend([f"### {item.get('claim', '观察结果')}", f"置信度：{item.get('confidence', 'low')}"])
        lines.extend(f"- 证据：{value}" for value in item.get("evidence", []))
        lines.extend(f"- 反向/缺失证据：{value}" for value in item.get("counter_evidence", []))
        lines.extend(f"- 限制：{value}" for value in item.get("limitations", []))
    lines.extend(["", "## 可验证假设"])
    for item in state.get("hypotheses", []):
        lines.extend([
            f"- 假设：{item.get('statement', '')}",
            f"  - 适用范围：{item.get('scope', '待确认')}",
            f"  - 置信度：{item.get('confidence', 'low')}",
            f"  - 验证方式：{item.get('validation', '后续同类视频观察相关指标')}",
        ])
    validations = state.get("followup_validations", [])
    if validations:
        lines.extend(["", "## 历史假设验证"])
        lines.extend(
            f"- {item.get('hypothesis_id')}: {item.get('status')}；证据：{'；'.join(item.get('evidence', [])) or '不足'}"
            for item in validations
        )
    lines.extend(["", "## 数据限制"])
    lines.extend(f"- {item}" for item in state.get("data_limitations", []))
    lines.extend(["", f"**总结：** {state.get('summary', '')}"])
    return {"report": "\n".join(lines).strip() + "\n"}


def _data_limitations(raw_data: dict[str, Any], selected: dict[str, Any], wants_comments: bool) -> list[str]:
    limitations = ["公开数据不能说明因果关系；报告中的解释需要后续视频或对照测试验证。"]
    if selected.get("unavailable"):
        limitations.append("所选指标缺失：" + ", ".join(selected["unavailable"]))
    limitations.append("当前 B 站公开接口不提供 5 秒跳出率、平均播放时长、完播率和真实留存曲线。")
    snapshots = raw_data.get("metric_snapshots", [])
    if len(snapshots) < 2:
        limitations.append("本次只有一个累计指标快照，无法计算发布后的增长趋势。")
    if wants_comments:
        collection = raw_data.get("comment_collection", {})
        limitations.append(
            f"评论分析基于抓取样本（{collection.get('fetched_count', len(raw_data.get('comments', [])))} 条），"
            f"平台显示 {collection.get('platform_total', '未知')} 条，不代表已采集全集。"
        )
    return limitations


def _requested_private_metrics(question: str) -> list[str]:
    terms = {
        "five_second_bounce_rate": ("5秒跳出率", "五秒跳出率", "跳出率"),
        "average_watch_duration": ("平均播放时长", "平均观看时长", "观看时长"),
        "completion_rate": ("完播率", "完播"),
        "retention_curve": ("留存", "流失曲线"),
    }
    return [key for key, matches in terms.items() if any(term in question for term in matches)]


def _validate_findings(
    result: dict[str, Any],
    evidence: list[str],
    selected_hypotheses: list[dict[str, Any]],
    limitations: list[str],
) -> dict[str, Any]:
    allowed_confidence = {"low", "medium", "high"}
    validated_explanations = []
    explanation_items = result.get("explanations", [])
    for item in explanation_items if isinstance(explanation_items, list) else []:
        if not isinstance(item, dict):
            continue
        citations_raw = item.get("evidence", [])
        citations = [str(value) for value in citations_raw if str(value) in evidence] if isinstance(citations_raw, list) else []
        counter_raw = item.get("counter_evidence", [])
        counter_catalog = set(evidence + limitations)
        counter_citations = [str(value) for value in counter_raw if str(value) in counter_catalog] if isinstance(counter_raw, list) else []
        confidence = item.get("confidence", "low")
        if confidence not in allowed_confidence or not citations:
            confidence = "low"
        validated_explanations.append({
            "claim": str(item.get("claim", "观测结果")),
            "evidence": citations,
            "counter_evidence": counter_citations,
            "confidence": "medium" if confidence == "high" and len(citations) < 2 else confidence,
            "limitations": [str(value) for value in item.get("limitations", [])] if isinstance(item.get("limitations", []), list) else [],
        })
    valid_hypothesis_ids = {str(item.get("id")) for item in selected_hypotheses if item.get("id")}
    validations = []
    validation_items = result.get("followup_validations", [])
    for item in validation_items if isinstance(validation_items, list) else []:
        if not isinstance(item, dict) or str(item.get("hypothesis_id")) not in valid_hypothesis_ids:
            continue
        status = item.get("status")
        validations.append({
            "hypothesis_id": str(item["hypothesis_id"]),
            "status": status if status in {"supported", "weakened", "inconclusive"} else "inconclusive",
            "evidence": [str(value) for value in item.get("evidence", []) if str(value) in evidence]
            if isinstance(item.get("evidence", []), list) else [],
        })
    return {
        "explanations": validated_explanations,
        "hypotheses": [
            {**item, "confidence": item.get("confidence") if item.get("confidence") in allowed_confidence else "low"}
            for item in (result.get("hypotheses", []) if isinstance(result.get("hypotheses", []), list) else []) if isinstance(item, dict)
        ],
        "followup_validations": validations,
        "summary": str(result.get("summary", "")),
    }


def _fallback_explanation(context: dict[str, Any]) -> dict[str, Any]:
    facts = list(context.get("evidence", []))
    limitations = context.get("limitations", [])
    hypotheses = []
    if facts:
        hypotheses.append({
            "statement": "在下一条同类型视频中只调整一个与问题相关的内容变量，观察相同指标是否按预期变化。",
            "scope": "同一创作者、相近主题与相近视频时长；当前尚未明确更细场景边界。",
            "confidence": "low",
            "validation": "记录调整前后的目标指标，并与至少一条相近视频对照。",
        })
    return {
        "explanations": [{
            "claim": "当前数据只支持描述已观测到的指标和评论信号，无法单独确定原因。",
            "evidence": facts,
            "counter_evidence": [],
            "confidence": "low",
            "limitations": limitations,
        }],
        "hypotheses": hypotheses,
        "followup_validations": [
            {"hypothesis_id": item.get("id"), "status": "inconclusive", "evidence": facts}
            for item in context.get("selected_hypotheses", [])
        ],
        "summary": "已整理可用证据；在获得更完整指标或后续验证数据前，不对原因作确定归因。",
    }
