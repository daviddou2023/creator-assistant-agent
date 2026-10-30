"""Deterministic signals extracted from the selected public comment sample."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any


POSITIVE_WORDS = {"有用", "喜欢", "收藏", "清楚", "真实", "实用", "学到", "共鸣", "期待", "专业"}
NEGATIVE_WORDS = {"看不懂", "太快", "啰嗦", "广告", "失望", "一般", "不准", "尴尬", "重复"}
STOP_WORDS = {"这个", "视频", "感觉", "真的", "可以", "还是", "就是", "一个", "我们", "你们", "内容"}


def analyze_comments(raw_data: dict[str, Any]) -> dict[str, Any]:
    comments = raw_data.get("comments", [])
    texts = [str(item.get("text", "")).strip() for item in comments if item.get("text")]
    keywords = Counter()
    sentiment = Counter()
    questions = []
    for text in texts:
        positive = any(word in text for word in POSITIVE_WORDS)
        negative = any(word in text for word in NEGATIVE_WORDS)
        sentiment["positive" if positive and not negative else "negative" if negative and not positive else "neutral"] += 1
        if "?" in text or "？" in text or text.startswith(("怎么", "如何", "为什么")):
            questions.append(text)
        keywords.update(_extract_keywords(text))
    return {
        "total": len(texts),
        "sentiment": {
            "positive": sentiment["positive"],
            "neutral": sentiment["neutral"],
            "negative": sentiment["negative"],
        },
        "hot_keywords": keywords.most_common(10),
        "questions": questions[:10],
        "representative_comments": texts[:10],
    }


def _extract_keywords(text: str) -> list[str]:
    words = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_+-]{2,}", text)
    return [word for word in words if word not in STOP_WORDS]
