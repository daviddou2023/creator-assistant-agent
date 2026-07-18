"""Report generation for the review agent."""

from __future__ import annotations

from typing import Any

from video_review_agent.memory import format_memories_for_report


def render_markdown_report(state: dict[str, Any]) -> str:
    raw_data = state.get("raw_data", {})
    metrics = state.get("metrics_summary", {})
    comments = state.get("comment_insights", {})
    content = state.get("content_insights", {})
    recommendations = state.get("recommendations", [])
    historical_preferences = state.get("historical_preferences", [])

    sentiment = comments.get("sentiment", {})
    hot_keywords = _format_pairs(comments.get("hot_keywords", []))
    signals = _format_pairs(content.get("presentation_signals", []))
    questions = comments.get("questions", [])
    top_liked_comments = raw_data.get("top_liked_comments", [])

    lines = [
        f"# 视频流量复盘报告：{raw_data.get('title', state.get('video_id', '未命名视频'))}",
        "",
        "## 1. 基础信息",
        f"- 视频 ID：{raw_data.get('video_id', state.get('video_id', ''))}",
        f"- 发布时间：{raw_data.get('published_at', '')}",
        f"- 分析窗口：发布后 {state.get('days_after_publish', '')} 天",
        f"- 数据区间：{metrics.get('first_snapshot', '无')} 至 {metrics.get('latest_snapshot', '无')}",
        f"- 创作者 ID：{state.get('creator_id', 'default_creator')}",
        "",
        "## 2. 流量表现",
        f"- 阅读量：{metrics.get('views', 0):,}",
        f"- 点赞量：{metrics.get('likes', 0):,}（点赞率 {metrics.get('like_rate', 0):.2%}）",
        f"- 转发量：{metrics.get('shares', 0):,}（转发率 {metrics.get('share_rate', 0):.2%}）",
        f"- 评论量：{metrics.get('comments', 0):,}（评论率 {metrics.get('comment_rate', 0):.2%}）",
        "",
        "## 3. 评论洞察",
        f"- 情绪分布：正向 {sentiment.get('positive', 0)}，中性 {sentiment.get('neutral', 0)}，负向 {sentiment.get('negative', 0)}",
        f"- 高频关键词：{hot_keywords or '暂无'}",
        f"- 高频问题：{'; '.join(questions) if questions else '暂无明显问题'}",
        f"- 点赞前五评论：{_format_top_liked_comments(top_liked_comments) if top_liked_comments else '暂无'}",
        "",
        "## 4. 兴趣与呈现方式判断",
        f"- 观众兴趣选题：{', '.join(content.get('audience_interest_topics', [])) or '暂无'}",
        f"- 有反馈的呈现方式：{signals or '暂无'}",
        f"- 核心判断：{content.get('core_takeaway', '')}",
        "",
        "## 5. 创作建议",
    ]

    lines.extend(f"- {item}" for item in recommendations)
    lines.extend(_render_memory_section(historical_preferences))
    return "\n".join(lines).strip() + "\n"


def _format_pairs(items: list[tuple[str, int]]) -> str:
    return ", ".join(f"{key}({value})" for key, value in items)


def _format_top_liked_comments(items: list[dict[str, Any]]) -> str:
    formatted = []
    for item in items[:5]:
        text = str(item.get("text", "")).replace("\n", " ").strip()
        if len(text) > 40:
            text = text[:40] + "..."
        formatted.append(f"{text}（{item.get('like', 0)}赞）")
    return "; ".join(formatted)


def _render_memory_section(memories: list[dict[str, Any]]) -> list[str]:
    if not memories:
        return [
            "",
            "## 6. 历史偏好参考",
            "- 暂无同一创作者的历史复盘经验。当前报告会在结束后写入向量记忆库。",
        ]

    lines = ["", "## 6. 历史偏好参考"]
    lines.extend(f"- {item}" for item in format_memories_for_report(memories))
    return lines
