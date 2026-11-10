"""Create the versioned, deterministic offline evaluation cases and fixtures."""

from __future__ import annotations

import json
import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"

BASE_COMMENTS = [
    ("c01", "这个内容后面还会继续讲吗？", "期待后续", "neutral"),
    ("c02", "讲得很清楚，学到了。", "认可内容", "positive"),
    ("c03", "希望能补充一个实际案例", "期待案例", "neutral"),
    ("c04", "这个方法我试过，确实有用", "认可方法", "positive"),
    ("c05", "听起来不错，想看后续", "期待后续", "positive"),
]

SCENARIOS = [
    ("normal", "为什么点赞率较高，但评论互动偏少？", 12, 10, True),
    ("normal", "播放和收藏表现怎么样？", 20, 15, False),
    ("normal", "转发率和互动率如何？", 8, 8, False),
    ("normal", "评论里观众主要在问什么？", 30, 25, True),
    ("normal", "点赞和投币表现如何？", 18, 17, False),
    ("normal", "整体互动情况如何？", 24, 20, True),
    ("low_comments", "这些评论反映了什么？", 2, 2, True),
    ("low_comments", "评论情绪偏正面还是负面？", 3, 2, True),
    ("low_comments", "为什么观众反馈很少？", 1, 1, True),
    ("empty_comments", "分析一下观众评论", 0, 0, True),
    ("empty_comments", "评论里有哪些问题？", 0, 0, True),
    ("empty_comments", "观众对内容的反馈如何？", 0, 0, True),
    ("duplicate_comments", "评论主题是什么？", 8, 3, True),
    ("duplicate_comments", "评论情绪如何？", 10, 4, True),
    ("duplicate_comments", "观众主要反馈了什么？", 12, 5, True),
    ("unavailable_metrics", "这条视频的完播率和5秒跳出率是多少？", 10, 8, False),
    ("unavailable_metrics", "平均观看时长是否偏低？", 11, 9, False),
    ("unavailable_metrics", "流失曲线说明了什么？", 9, 7, False),
    ("unavailable_metrics", "为什么完播率低但点赞多？", 15, 12, True),
    ("no_comments", "播放量和点赞量各是多少？", 14, 12, False),
    ("no_comments", "收藏率怎么样？", 19, 17, False),
    ("no_comments", "点赞与转发的比例如何？", 21, 20, False),
    ("tool_failure", "分析一下播放量和点赞量", 5, 0, False),
    ("tool_failure", "抓取评论并总结观众反馈", 5, 0, True),
]


def build(force: bool = False) -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    cases_path = ROOT / "cases.jsonl"
    if cases_path.exists() and not force:
        raise SystemExit("eval/cases.jsonl already exists; use --force only to regenerate and overwrite manual annotations.")
    cases = []
    for index, (scenario, question, view_delta, comment_total, comments_requested) in enumerate(SCENARIOS, 1):
        case_id = f"{scenario}_{index:02d}"
        video_id = f"eval-{index:03d}"
        is_failure = scenario == "tool_failure"
        path = FIXTURES / f"{case_id}.json"
        if not is_failure:
            comments = []
            if scenario not in {"empty_comments", "no_comments"}:
                source = BASE_COMMENTS[:min(comment_total, len(BASE_COMMENTS))]
                if scenario == "duplicate_comments":
                    source = [BASE_COMMENTS[0], BASE_COMMENTS[1], BASE_COMMENTS[0], BASE_COMMENTS[2], BASE_COMMENTS[1]]
                if scenario == "low_comments":
                    source = BASE_COMMENTS[:comment_total]
                comments = [
                    {"comment_id": cid, "text": text, "created_at": f"2026-10-{i + 2:02d}T00:00:00Z", "like": i}
                    for i, (cid, text, _topic, _sentiment) in enumerate(source)
                ]
            metrics = {
                "views": 10000 + index * 100,
                "likes": 800 + index * 10,
                "shares": 40 + index,
                "favorites": 90 + index,
                "coins": 25 + index,
                "danmaku": 30 + index,
                "reply": comment_total,
            }
            fixture = {"videos": [{
                "video_id": video_id,
                "title": f"固定评测案例 {index:02d}",
                "description": f"用于 {scenario} 场景的离线评测快照。",
                "published_at": "2026-10-01T00:00:00Z",
                "metric_snapshots": [{"captured_at": "2026-10-10T00:00:00Z", **metrics}],
                "comments": comments,
                "comment_collection": {
                    "platform_total": comment_total,
                    "fetched_count": len(comments),
                    "sample_limit": 50,
                },
            }]}
            path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            fetched_count = len(comments) if comments_requested else 0
            effective_count = len({c["text"].casefold() for c in comments}) if comments_requested else 0
        else:
            path = FIXTURES / f"{case_id}_missing.json"
            fetched_count = effective_count = 0

        expected_metrics = ["views"]
        q = question
        if any(word in q for word in ("点赞", "点赞率")):
            expected_metrics.append("likes")
        if any(word in q for word in ("转发", "互动率")):
            expected_metrics.append("shares")
        if "互动率" in q:
            expected_metrics.extend(["likes", "shares", "reply"])
        if "整体互动" in q:
            expected_metrics.extend(["likes", "shares", "reply"])
        if "收藏" in q:
            expected_metrics.append("favorites")
        if "投币" in q:
            expected_metrics.append("coins")
        if comments_requested and any(word in q for word in ("评论", "观众", "反馈", "为什么")):
            expected_metrics.append("reply")
        expected_metrics = list(dict.fromkeys(expected_metrics))
        expected_unavailable = []
        for key, terms in {
            "five_second_bounce_rate": ("5秒跳出",),
            "average_watch_duration": ("平均观看时长",),
            "completion_rate": ("完播率",),
            "retention_curve": ("流失曲线",),
        }.items():
            if any(term in question for term in terms):
                expected_unavailable.append(key)
        derived = {}
        if metrics["views"] > 0:
            if "likes" in expected_metrics:
                derived["like_rate"] = round(metrics["likes"] / metrics["views"], 4)
            if "shares" in expected_metrics:
                derived["share_rate"] = round(metrics["shares"] / metrics["views"], 4)
            interactions = [metrics[key] for key in ("likes", "shares", "reply") if key in expected_metrics]
            if interactions and any(key in expected_metrics for key in ("likes", "shares", "reply")):
                derived["engagement_rate"] = round(sum(interactions) / metrics["views"], 4)

        comments = [] if is_failure or not comments_requested else (
            [] if scenario == "empty_comments" else BASE_COMMENTS[:comment_total]
        )
        if scenario == "duplicate_comments":
            comments = [BASE_COMMENTS[0], BASE_COMMENTS[1], BASE_COMMENTS[0], BASE_COMMENTS[2], BASE_COMMENTS[1]]
        comment_labels = [
            {"comment_id": item[0], "topic": item[2], "sentiment": item[3]}
            for item in comments
        ]
        acceptable_claims = [
            f"当前固定快照的播放量为 {metrics['views']}。" if not is_failure else "本案例的数据源不可用，无法核实视频指标。"
        ]
        unsupported_claims = []
        if scenario == "unavailable_metrics":
            acceptable_claims.append("本案例请求了 B 站公开数据未提供的创作者后台指标，应明确说明缺失。")
            unsupported_claims.append("根据公开累计互动数据断言完播率、跳出率或流失曲线的具体数值。")
        elif scenario == "empty_comments":
            acceptable_claims.append("当前评论样本为空，无法从评论判断观众主题或情绪。")
            unsupported_claims.append("声称评论普遍正面、负面或存在某个高频主题。")
        elif scenario == "low_comments":
            acceptable_claims.append("评论样本很少，观察只能描述当前样本，不能代表全部观众。")
            unsupported_claims.append("把少量评论当作全体观众的稳定偏好。")
        elif scenario == "duplicate_comments":
            acceptable_claims.append("报告应区分抓取评论数和去重后的有效评论数。")
            unsupported_claims.append("把重复评论计作多条独立用户反馈。")
        elif scenario == "tool_failure":
            unsupported_claims.append("在数据采集失败时编造指标或评论内容。")
        elif scenario == "no_comments":
            unsupported_claims.append("把未采集评论解释为没有观众反馈。")
        else:
            acceptable_claims.append("互动率等派生指标应由本案例快照中的原始数据计算。")
            unsupported_claims.append("仅凭单条视频的累计数据断言某种内容特征造成了互动表现。")
        acceptable_hypotheses = [] if is_failure else [
            "提出一个适用于后续同类视频、可观察目标指标并尽量只调整一个内容变量的假设；不要把本条视频的相关性写成已证实因果。"
        ]
        cases.append({
            "schema_version": "1.0",
            "case_id": case_id,
            "scenario": scenario,
            "annotation_status": "draft_needs_human_review",
            "request": {
                "video_id": video_id,
                "platform": "json",
                "source_path": str(path.relative_to(ROOT.parent)).replace("\\", "/"),
                "creator_id": "eval_creator",
                "days_after_publish": 30,
                "max_comments": 50,
                "user_question": question,
            },
            "gold": {
                "required_metric_keys": expected_metrics,
                "expected_values": metrics if not is_failure else {},
                "expected_derived": derived if not is_failure else {},
                "optional_metric_keys": [],
                "unnecessary_metric_keys": [k for k in ("views", "likes", "shares", "favorites", "coins", "danmaku", "reply") if k not in expected_metrics],
                "comments_required": comments_requested,
                "expected_comment_counts": {
                    "platform_total": comment_total,
                    "fetched": fetched_count,
                    "effective": effective_count,
                },
                "unavailable_metrics_that_must_be_disclosed": expected_unavailable,
                "expected_failure": is_failure,
                "comment_labels": comment_labels,
                "acceptable_claims": acceptable_claims,
                "unsupported_claims": unsupported_claims,
                "acceptable_hypotheses": acceptable_hypotheses,
                "human_review": {
                    "comment_topics_reviewed": False,
                    "claim_support_reviewed": False,
                    "reviewer": None,
                    "notes": "请审核评论主题、情绪标签及可支持/不支持的结论后更新。",
                },
            },
        })
    cases_path.write_text(
        "".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases), encoding="utf-8"
    )
    print(f"Wrote {len(cases)} cases and deterministic fixtures to {ROOT}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="overwrite cases.jsonl, including manual annotation changes")
    build(force=parser.parse_args().force)
