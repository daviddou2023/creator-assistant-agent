"""Run the fixed benchmark against the LangGraph agent and/or a rule baseline."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from video_review_agent.analytics import analyze_comments
from video_review_agent.collectors import collect_video_data
from video_review_agent.tools import clean_comments, get_metrics_by_keys
from video_review_agent.workflow import run_video_review

EVAL_DIR = Path(__file__).resolve().parent


def load_cases() -> list[dict[str, Any]]:
    cases_path = EVAL_DIR / "cases.jsonl"
    if not cases_path.exists():
        raise SystemExit("Missing eval/cases.jsonl. Run: python eval/build_dataset.py")
    return [json.loads(line) for line in cases_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_rules(case: dict[str, Any]) -> dict[str, Any]:
    request = case["request"]
    question = request["user_question"]
    keys = _rule_metric_keys(question)
    wants_comments = bool(re.search(r"评论|观众|反馈|为什么", question)) or ("互动" in question and "率" not in question)
    try:
        raw = collect_video_data(
            video_id=request["video_id"],
            source_path=request["source_path"],
            days_after_publish=request["days_after_publish"],
            platform="json",
            max_comments=request["max_comments"],
            include_comments=wants_comments,
        )
        metrics = get_metrics_by_keys(raw, keys)
        comments, cleaning = clean_comments(raw.get("comments", [])) if wants_comments else ([], {"removed_empty": 0, "removed_duplicate": 0})
        insights = analyze_comments({"comments": comments}) if comments else {}
        counts = dict(raw.get("comment_collection", {}))
        counts.update({
            "requested": wants_comments,
            "fetched": len(raw.get("comments", [])),
            "effective": len(comments),
            "removed_empty": cleaning["removed_empty"],
            "removed_duplicate": cleaning["removed_duplicate"],
        })
        unavailable = _unavailable_from_question(question)
        metrics["unavailable"] = list(dict.fromkeys([*metrics.get("unavailable", []), *unavailable]))
        return {
            "selected_metrics": metrics,
            "todos": ([{"type": "metrics", "keys": keys}] + ([{"type": "fetch_comments"}] if wants_comments else [])),
            "comment_counts": counts,
            "comment_insights": insights,
            "evidence": _evidence(metrics, insights),
            "explanations": [],
            "failed_tasks": [],
        }
    except Exception as exc:
        todos = [{"type": "metrics", "keys": keys}] + ([{"type": "fetch_comments"}] if wants_comments else [])
        return {"todos": todos, "failed_tasks": [f"{type(exc).__name__}: {exc}"]}


def run_agent(case: dict[str, Any]) -> dict[str, Any]:
    request = case["request"]
    state = run_video_review(
        video_id=request["video_id"],
        user_question=request["user_question"],
        platform="json",
        source_path=request["source_path"],
        creator_id=request["creator_id"],
        days_after_publish=request["days_after_publish"],
        max_comments=request["max_comments"],
        selected_hypotheses=[],
    )
    return dict(state)


def score(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    gold = case["gold"]
    metrics = result.get("selected_metrics", {})
    values = metrics.get("values", {})
    todos = result.get("todos", [])
    selected = {
        key for task in todos if task.get("type") == "metrics" for key in task.get("keys", [])
    }
    comments_selected = any(task.get("type") == "fetch_comments" for task in todos)
    required = set(gold.get("required_metric_keys", []))
    expected_values = gold.get("expected_values", {})
    expected_failure = bool(gold.get("expected_failure"))
    failed = bool(result.get("failed_tasks"))
    missing_values = [] if expected_failure and failed else [key for key in required if key not in values]
    wrong_values = {
        key: {"expected": value, "actual": values.get(key)}
        for key, value in expected_values.items()
        if key in selected and values.get(key) != value
    }
    derived = metrics.get("derived", {})
    expected_derived = gold.get("expected_derived", {})
    wrong_derived = {
        key: {"expected": value, "actual": derived.get(key)}
        for key, value in expected_derived.items()
        if not expected_failure and derived.get(key) != value
    }
    counts = result.get("comment_counts", {})
    expected_counts = gold.get("expected_comment_counts", {})
    count_errors = {} if expected_failure and failed else {
        key: {"expected": value, "actual": counts.get(key)}
        for key, value in expected_counts.items()
        if counts.get(key) != value
    }
    unavailable = set(metrics.get("unavailable", []))
    missing_unavailable = sorted(set(gold.get("unavailable_metrics_that_must_be_disclosed", [])) - unavailable)
    evidence = set(result.get("evidence", []))
    invalid_citations = [
        citation
        for finding in result.get("explanations", [])
        for citation in finding.get("evidence", [])
        if citation not in evidence
    ]
    checks = {
        "required_metrics_selected": not (required - selected),
        "no_unnecessary_metrics_selected": not (selected & set(gold.get("unnecessary_metric_keys", []))),
        "comment_task_selected_appropriately": comments_selected == bool(gold.get("comments_required")),
        "expected_metric_values": (expected_failure and failed) or (not missing_values and not wrong_values),
        "expected_derived_metrics": (expected_failure and failed) or not wrong_derived,
        "comment_counts": (expected_failure and failed) or not count_errors,
        "unavailable_metrics_disclosed": not missing_unavailable,
        "citations_exist_in_evidence": not invalid_citations,
        "failure_matches_case": failed == bool(gold.get("expected_failure")),
    }
    passed = sum(checks.values())
    return {
        "case_id": case["case_id"],
        "checks": checks,
        "score": round(passed / len(checks), 4),
        "details": {
            "selected_metric_keys": sorted(selected),
            "missing_required_metric_keys": sorted(required - selected),
            "missing_metric_values": missing_values,
            "wrong_metric_values": wrong_values,
            "wrong_derived_metrics": wrong_derived,
            "comment_count_errors": count_errors,
            "missing_unavailable_metrics": missing_unavailable,
            "invalid_citations": invalid_citations,
            "failed_tasks": result.get("failed_tasks", []),
            "human_review_required": not (
                gold.get("human_review", {}).get("comment_topics_reviewed")
                and gold.get("human_review", {}).get("claim_support_reviewed")
            ),
        },
    }


def _rule_metric_keys(question: str) -> list[str]:
    keys = ["views"]
    if "整体互动" in question or "互动率" in question:
        keys.extend(["likes", "shares", "reply"])
    for key, terms in {
        "likes": ("点赞",),
        "shares": ("转发", "互动率"),
        "favorites": ("收藏",),
        "coins": ("投币",),
        "reply": ("评论", "互动率", "互动偏少", "观众", "反馈", "为什么"),
    }.items():
        if any(term in question for term in terms):
            keys.append(key)
    return list(dict.fromkeys(keys))


def _unavailable_from_question(question: str) -> list[str]:
    terms = {
        "five_second_bounce_rate": ("5秒跳出",),
        "average_watch_duration": ("平均观看时长",),
        "completion_rate": ("完播率",),
        "retention_curve": ("流失曲线",),
    }
    return [key for key, words in terms.items() if any(word in question for word in words)]


def _evidence(metrics: dict[str, Any], comments: dict[str, Any]) -> list[str]:
    result = [f"{key}: {value}" for key, value in metrics.get("values", {}).items()]
    result.extend(f"{key}: {value:.2%}（按已取指标计算）" for key, value in metrics.get("derived", {}).items())
    if comments:
        result.append(f"有效评论样本数 {comments.get('total', 0)}")
        result.append(f"评论高频词 {comments.get('hot_keywords', [])}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("rules", "agent", "both"), default="both")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    cases = load_cases()
    modes = ("rules", "agent") if args.mode == "both" else (args.mode,)
    output = []
    with tempfile.TemporaryDirectory(prefix="video-review-eval-") as temp:
        os.environ["VIDEO_REVIEW_EXPERIENCE_PATH"] = str(Path(temp) / "experiences.json")
        for mode in modes:
            records = []
            for case in cases:
                result = run_rules(case) if mode == "rules" else run_agent(case)
                records.append({"case_id": case["case_id"], "result": result, "evaluation": score(case, result)})
            mean_score = sum(item["evaluation"]["score"] for item in records) / len(records)
            failed_checks = sum(
                not passed
                for item in records
                for passed in item["evaluation"]["checks"].values()
            )
            output.append({"mode": mode, "case_count": len(records), "mean_score": round(mean_score, 4), "failed_checks": failed_checks, "cases": records})
    rendered = json.dumps({"schema_version": "1.0", "results": output}, ensure_ascii=False, indent=2)
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered + "\n", encoding="utf-8")
    summary = [
        {"mode": item["mode"], "case_count": item["case_count"], "mean_score": item["mean_score"], "failed_checks": item["failed_checks"]}
        for item in output
    ]
    print(json.dumps({"schema_version": "1.0", "summary": summary, "output_file": args.output or None}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
