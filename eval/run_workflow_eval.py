"""Check bounded replanning and user-correction reruns in the current workflow."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Keep workflow checks deterministic and independent of credentials in .env.
os.environ["VIDEO_REVIEW_LLM_API_KEY_ENV"] = "VIDEO_REVIEW_EVAL_NO_KEY"
os.environ["VIDEO_REVIEW_EVAL_NO_KEY"] = ""

from video_review_agent.service_runtime import create_app
from video_review_agent.workflow import build_graph

EVAL_DIR = Path(__file__).resolve().parent


def load_cases() -> list[dict[str, Any]]:
    path = EVAL_DIR / "workflow_cases.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_replan_case(case: dict[str, Any]) -> dict[str, Any]:
    state: dict[str, Any] = {}
    node_names = []
    for event in build_graph().stream(case["request"], stream_mode="updates"):
        node, delta = next(iter(event.items()))
        node_names.append(node)
        if isinstance(delta, dict):
            state.update(delta)

    replan_count = node_names.count("replan")
    expected = case["expect"]
    checks = {
        "replan_triggered": replan_count >= expected["minimum_replan_nodes"],
        "replan_attempts_bounded": replan_count <= expected["maximum_replan_nodes"],
        "expected_attempt_count": state.get("replan_attempts") == expected["replan_attempts"],
        "report_generated": bool(state.get("report")) if expected["report_required"] else True,
        "workflow_terminated_at_report": bool(node_names) and node_names[-1] == "report",
    }
    return {
        "case_id": case["case_id"],
        "checks": checks,
        "details": {
            "nodes": node_names,
            "replan_nodes": replan_count,
            "replan_attempts": state.get("replan_attempts"),
            "report_generated": bool(state.get("report")),
            "data_limitations": state.get("data_limitations", []),
        },
    }


def run_feedback_case(case: dict[str, Any], client: Any, timeout_seconds: float) -> dict[str, Any]:
    started = client.post("/api/reviews", json=case["request"])
    if started.status_code != 202:
        raise RuntimeError(f"initial review rejected: {started.status_code} {started.get_data(as_text=True)}")
    first_id = started.get_json()["job_id"]
    initial = _wait_for_review(client, first_id, timeout_seconds)
    if initial["status"] != "completed":
        raise RuntimeError(f"initial review did not complete: {initial['status']}")

    feedback = client.post(
        f"/api/reviews/{first_id}/feedback",
        json={"correction": case["correction"]},
    )
    if feedback.status_code != 202:
        raise RuntimeError(f"feedback rerun rejected: {feedback.status_code} {feedback.get_data(as_text=True)}")
    second_id = feedback.get_json()["job_id"]
    rerun = _wait_for_review(client, second_id, timeout_seconds)
    if rerun["status"] != "completed":
        raise RuntimeError(f"feedback rerun did not complete: {rerun['status']}")

    initial_result = initial["result"]
    rerun_result = rerun["result"]
    initial_title = _report_title(initial_result.get("report", ""))
    rerun_title = _report_title(rerun_result.get("report", ""))
    observations = rerun_result.get("observations", [])
    rerun_report = rerun_result.get("report", "")
    expected = case["expect"]
    checks = {
        "new_job_created": first_id != second_id,
        "initial_comment_plan_matches": initial_result.get("comment_counts", {}).get("requested") is expected["initial_comments_requested"],
        "rerun_comment_plan_matches": rerun_result.get("comment_counts", {}).get("requested") is expected["rerun_comments_requested"],
        "correction_reached_new_run": case["correction"] in rerun_report
        if expected["correction_in_report_question"] else True,
        "same_video_kept": initial_title == rerun_title and bool(initial_title)
        if expected["same_video_report_title"] else True,
    }
    return {
        "case_id": case["case_id"],
        "checks": checks,
        "details": {
            "initial_job_id": first_id,
            "rerun_job_id": second_id,
            "initial_report_title": initial_title,
            "rerun_report_title": rerun_title,
            "correction_in_report": case["correction"] in rerun_report,
            "initial_comment_counts": initial_result.get("comment_counts", {}),
            "rerun_comment_counts": rerun_result.get("comment_counts", {}),
            "rerun_observations": observations,
        },
    }


def _wait_for_review(client: Any, job_id: str, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = client.get(f"/api/reviews/{job_id}")
        if response.status_code != 200:
            raise RuntimeError(f"review lookup failed: {response.status_code}")
        result = response.get_json()
        if result["status"] in {"completed", "failed"}:
            return result
        time.sleep(0.05)
    raise TimeoutError(f"review job {job_id} exceeded {timeout_seconds} seconds")


def _report_title(report: str) -> str:
    return report.splitlines()[0].strip() if report.splitlines() else ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="", help="optional path for detailed JSON results")
    parser.add_argument("--timeout", type=float, default=30.0, help="per review job timeout in seconds")
    args = parser.parse_args()

    cases = load_cases()
    results = []
    with tempfile.TemporaryDirectory(prefix="creator-workflow-eval-") as temp:
        os.environ["VIDEO_REVIEW_EXPERIENCE_PATH"] = str(Path(temp) / "experiences.json")
        client = create_app().test_client()
        for case in cases:
            if case["kind"] == "replan_failure":
                results.append(run_replan_case(case))
            elif case["kind"] == "feedback_rerun":
                results.append(run_feedback_case(case, client, args.timeout))
            else:
                raise ValueError(f"Unsupported workflow case kind: {case['kind']}")

    for item in results:
        checks = item["checks"]
        item["score"] = round(sum(checks.values()) / len(checks), 4) if checks else 1.0
    payload = {"schema_version": "1.0", "case_count": len(results), "cases": results}
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered + "\n", encoding="utf-8")
    summary = {
        "case_count": len(results),
        "passed_checks": sum(sum(item["checks"].values()) for item in results),
        "total_checks": sum(len(item["checks"]) for item in results),
        "all_passed": all(all(item["checks"].values()) for item in results),
        "output_file": args.output or None,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
