"""Review workflow routes: PR comments/patch suggestions and feedback learning."""

from __future__ import annotations

import os
from pathlib import Path

from services.review_feedback import build_feedback_insights, record_feedback
from xray.fixer import FIXABLE_RULES, preview_fix


def _resolve_file(directory: str, file_path: str) -> str:
    p = Path(file_path)
    if p.is_file():
        return str(p)
    joined = Path(directory).resolve() / file_path
    return str(joined)


def handle_pr_comments(body: dict, handler):
    directory = body.get("directory", "")
    findings = body.get("findings", [])
    if not directory or not os.path.isdir(directory):
        return {"error": f"Invalid directory: {directory}"}, 400
    if not isinstance(findings, list):
        return {"error": "findings must be a list"}, 400

    max_items = int(body.get("max_items", 25) or 25)
    if max_items < 1:
        max_items = 1
    if max_items > 100:
        max_items = 100

    ranked = sorted(
        findings,
        key=lambda f: (
            {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(str(f.get("severity", "LOW")), 3),
            str(f.get("file", "")),
            int(f.get("line", 0) or 0),
        ),
    )[:max_items]

    comments = []
    markdown_lines = ["## X-Ray Review Suggestions", ""]

    for f in ranked:
        file_path = str(f.get("file", ""))
        line = int(f.get("line", 0) or 0)
        rule_id = str(f.get("rule_id", "UNKNOWN"))
        severity = str(f.get("severity", "LOW"))
        desc = str(f.get("description", ""))
        fix_hint = str(f.get("fix_hint", ""))

        patch_diff = ""
        if rule_id in FIXABLE_RULES and file_path:
            preview = preview_fix(
                {
                    "rule_id": rule_id,
                    "file": _resolve_file(directory, file_path),
                    "line": line,
                    "matched_text": str(f.get("matched_text", "")),
                    "fix_hint": fix_hint,
                }
            )
            if preview.get("fixable") and preview.get("diff"):
                patch_diff = str(preview["diff"])[:4000]

        item = {
            "file": file_path,
            "line": line,
            "rule_id": rule_id,
            "severity": severity,
            "description": desc,
            "fix_hint": fix_hint,
            "patch_diff": patch_diff,
        }
        comments.append(item)

        markdown_lines.append(f"- **[{severity}] {rule_id}** in `{file_path}:{line}`")
        markdown_lines.append(f"  - {desc}")
        if fix_hint:
            markdown_lines.append(f"  - Suggested fix: {fix_hint}")
        if patch_diff:
            markdown_lines.append("  - Quick patch suggestion:")
            markdown_lines.append("```diff")
            markdown_lines.append(patch_diff)
            markdown_lines.append("```")
        markdown_lines.append("")

    return {
        "total_input": len(findings),
        "total_comments": len(comments),
        "comments": comments,
        "markdown": "\n".join(markdown_lines),
    }, 200


def handle_feedback_record(body: dict, handler):
    directory = body.get("directory", "")
    if not directory or not os.path.isdir(directory):
        return {"error": f"Invalid directory: {directory}"}, 400
    result = record_feedback(directory, body.get("feedback", {}))
    if not result.get("ok"):
        return result, 400
    return result, 200


def handle_feedback_insights(body: dict, handler):
    directory = body.get("directory", "")
    if not directory or not os.path.isdir(directory):
        return {"error": f"Invalid directory: {directory}"}, 400
    return build_feedback_insights(directory), 200


POST_ROUTES = {
    "/api/pr-comments": handle_pr_comments,
    "/api/feedback": handle_feedback_record,
    "/api/feedback-insights": handle_feedback_insights,
}
