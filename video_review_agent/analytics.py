"""Deterministic analytics used by the review agent."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any


POSITIVE_WORDS = {"有用", "喜欢", "收藏", "清楚", "真实", "实用", "学到", "共鸣", "期待", "专业"}
NEGATIVE_WORDS = {"看不懂", "太快", "啰嗦", "广告", "失望", "一般", "不准", "尴尬", "重复"}
PRESENTATION_WORDS = {
    "开头": "开头钩子",
    "节奏": "叙事节奏",
    "字幕": "字幕信息",
    "案例": "案例拆解",
    "对比": "前后对比",
    "步骤": "步骤化讲解",
    "镜头": "镜头呈现",
    "声音": "声音表现",
}


def summarize_metrics(raw_data: dict[str, Any]) -> dict[str, Any]:
    snapshots = sorted(raw_data.get("metric_snapshots", []), key=lambda item: item["captured_at"])
    if not snapshots:
        return {
            "views": 0,
            "likes": 0,
            "shares": 0,
            "comments": len(raw_data.get("comments", [])),
            "like_rate": 0,
            "share_rate": 0,
            "growth": {},
        }

    first = snapshots[0]
    latest = snapshots[-1]
    views = int(latest.get("views", 0))
    likes = int(latest.get("likes", 0))
    shares = int(latest.get("shares", 0))
    comment_count = len(raw_data.get("comments", []))

    return {
        "views": views,
        "likes": likes,
        "shares": shares,
        "comments": comment_count,
        "like_rate": _ratio(likes, views),
        "share_rate": _ratio(shares, views),
        "comment_rate": _ratio(comment_count, views),
        "growth": {
            "views": views - int(first.get("views", 0)),
            "likes": likes - int(first.get("likes", 0)),
            "shares": shares - int(first.get("shares", 0)),
        },
        "first_snapshot": first.get("captured_at"),
        "latest_snapshot": latest.get("captured_at"),
    }


def analyze_comments(raw_data: dict[str, Any]) -> dict[str, Any]:
    comments = raw_data.get("comments", [])
    texts = [str(item.get("text", "")).strip() for item in comments if item.get("text")]
    keyword_counter = Counter()
    positive = 0
    negative = 0
    questions = []
    quotes = []

    for text in texts:
        if any(word in text for word in POSITIVE_WORDS):
            positive += 1
        if any(word in text for word in NEGATIVE_WORDS):
            negative += 1
        if "?" in text or "？" in text or text.startswith("怎么") or text.startswith("如何"):
            questions.append(text)
        quotes.append(text)
        keyword_counter.update(_extract_keywords(text))

    neutral = max(len(texts) - positive - negative, 0)
    return {
        "total": len(texts),
        "sentiment": {"positive": positive, "neutral": neutral, "negative": negative},
        "hot_keywords": keyword_counter.most_common(10),
        "questions": questions[:5],
        "representative_comments": quotes[:6],
    }


def infer_content_insights(raw_data: dict[str, Any], comment_insights: dict[str, Any]) -> dict[str, Any]:
    title = raw_data.get("title", "")
    description = raw_data.get("description", "")
    comments_text = " ".join(comment for comment in comment_insights.get("representative_comments", []))
    corpus = f"{title} {description} {comments_text}"

    presentation_hits = Counter()
    for word, label in PRESENTATION_WORDS.items():
        if word in corpus:
            presentation_hits[label] += corpus.count(word)

    interest_keywords = [keyword for keyword, _count in comment_insights.get("hot_keywords", [])[:6]]
    return {
        "audience_interest_topics": interest_keywords,
        "presentation_signals": presentation_hits.most_common(),
        "core_takeaway": _build_takeaway(interest_keywords, presentation_hits),
    }


def build_recommendations(metrics: dict[str, Any], comments: dict[str, Any], content: dict[str, Any]) -> list[str]:
    recommendations = []

    if metrics.get("share_rate", 0) >= 0.02:
        recommendations.append("保留可转发的观点密度，在标题和结尾明确一句可被复述的结论。")
    else:
        recommendations.append("增加可转发的信息点，例如清单、对比结论或一句高记忆度金句。")

    if metrics.get("like_rate", 0) >= 0.06:
        recommendations.append("当前内容的价值感较强，可围绕同一选题做系列化延展。")
    else:
        recommendations.append("前 3 秒需要更快交代收益，让观众先知道继续看的理由。")

    if comments.get("questions"):
        recommendations.append("把高频问题拆成下一条视频的选题，并在评论区置顶承接互动。")

    topics = content.get("audience_interest_topics", [])[:3]
    if topics:
        recommendations.append(f"优先测试这些选题关键词：{', '.join(topics)}。")

    signals = [label for label, _count in content.get("presentation_signals", [])[:3]]
    if signals:
        recommendations.append(f"呈现方式上继续强化：{', '.join(signals)}。")

    return recommendations


def _extract_keywords(text: str) -> list[str]:
    words = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_+-]{2,}", text)
    stop_words = {"这个", "视频", "感觉", "真的", "可以", "还是", "就是", "一个", "我们", "你们", "内容"}
    return [word for word in words if word not in stop_words]


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0
    return round(numerator / denominator, 4)


def _build_takeaway(keywords: list[str], presentation_hits: Counter[str]) -> str:
    if keywords and presentation_hits:
        top_signal = presentation_hits.most_common(1)[0][0]
        return f"观众更关注 {'、'.join(keywords[:3])}，并对{top_signal}有明显反馈。"
    if keywords:
        return f"观众兴趣集中在 {'、'.join(keywords[:3])}。"
    return "评论样本较少，建议继续积累数据后再判断稳定兴趣。"
