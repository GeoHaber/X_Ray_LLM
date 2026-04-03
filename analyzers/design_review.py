"""
LLM-Powered Design Review — Feeds architecture data to an LLM for
high-level design analysis and recommendations.
Falls back to rule-based analysis when no LLM is available.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def _build_architecture_summary(directory: str) -> dict:
    """Build a compact architecture summary for LLM consumption."""
    from analyzers import (
        analyze_connections,
        check_project_health,
        detect_code_smells,
        detect_dead_functions,
        detect_duplicates,
    )

    summary = {}

    try:
        conn = analyze_connections(directory)
        summary["connections"] = {
            "wired": conn.get("summary", {}).get("wired_count", 0),
            "orphan_ui": conn.get("summary", {}).get("orphan_ui_count", 0),
            "orphan_backend": conn.get("summary", {}).get("orphan_backend_count", 0),
            "frameworks": conn.get("frameworks_detected", []),
        }
    except Exception:
        summary["connections"] = {"error": "failed"}

    try:
        health = check_project_health(directory)
        summary["health"] = {
            "score": health.get("score", 0),
            "grade": health.get("grade", "?"),
        }
    except Exception:
        summary["health"] = {"error": "failed"}

    try:
        smells = detect_code_smells(directory)
        if isinstance(smells, dict):
            items = smells.get("smells", [])
        else:
            items = smells.smells if hasattr(smells, "smells") else []
        summary["smells"] = {
            "total": len(items),
            "top_types": _top_n(items, "type", 5),
        }
    except Exception:
        summary["smells"] = {"error": "failed"}

    try:
        dead = detect_dead_functions(directory)
        if isinstance(dead, dict):
            fns = dead.get("dead_functions", [])
        else:
            fns = dead.functions if hasattr(dead, "functions") else []
        summary["dead_code"] = {"count": len(fns)}
    except Exception:
        summary["dead_code"] = {"error": "failed"}

    try:
        dupes = detect_duplicates(directory)
        groups = dupes.get("duplicate_groups", []) if isinstance(dupes, dict) else []
        summary["duplicates"] = {"groups": len(groups)}
    except Exception:
        summary["duplicates"] = {"error": "failed"}

    return summary


def _top_n(items: list, key: str, n: int) -> list[str]:
    """Get top N most common values for a key."""
    counts: dict[str, int] = {}
    for item in items:
        val = item.get(key, "unknown") if isinstance(item, dict) else getattr(item, key, "unknown")
        counts[val] = counts.get(val, 0) + 1
    return sorted(counts, key=lambda k: -counts[k])[:n]


def _count_files(directory: str) -> dict[str, int]:
    """Count files by extension."""
    from analyzers._shared import _SKIP_DIRS
    counts: dict[str, int] = {}
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = [d for d in dirnames
                       if d not in _SKIP_DIRS and not d.startswith((".venv", "node_modules"))]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext in (".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".rs"):
                counts[ext] = counts.get(ext, 0) + 1
    return counts


def _rule_based_review(arch: dict, file_counts: dict) -> list[dict]:
    """Fallback: rule-based design review when no LLM available."""
    findings = []

    # Connection health
    conn = arch.get("connections", {})
    orphan_ui = conn.get("orphan_ui", 0)
    orphan_be = conn.get("orphan_backend", 0)
    if orphan_ui > 5:
        findings.append({
            "category": "connectivity",
            "severity": "HIGH",
            "title": "Many frontend orphans detected",
            "detail": f"{orphan_ui} frontend API calls have no backend handler. "
                      f"This indicates dead UI code or missing backend implementations.",
            "recommendation": "Audit orphan frontend calls and either implement handlers or remove dead UI code.",
        })
    if orphan_be > 10:
        findings.append({
            "category": "connectivity",
            "severity": "MEDIUM",
            "title": "Many unused backend endpoints",
            "detail": f"{orphan_be} backend routes have no frontend callers. "
                      f"These may be dead code or undiscovered API surface.",
            "recommendation": "Document or deprecate unused endpoints. Consider API versioning.",
        })

    # Health
    health = arch.get("health", {})
    score = health.get("score", 100)
    if score < 50:
        findings.append({
            "category": "health",
            "severity": "HIGH",
            "title": f"Low project health score ({score}%)",
            "detail": "Project health is below acceptable threshold.",
            "recommendation": "Address critical findings, improve test coverage, and fix code smells.",
        })

    # Code smells
    smells = arch.get("smells", {})
    smell_count = smells.get("total", 0)
    if smell_count > 20:
        findings.append({
            "category": "quality",
            "severity": "MEDIUM",
            "title": f"{smell_count} code smells detected",
            "detail": f"Top smell types: {', '.join(smells.get('top_types', []))}",
            "recommendation": "Prioritize god classes and high-complexity functions for refactoring.",
        })

    # Dead code
    dead = arch.get("dead_code", {})
    dead_count = dead.get("count", 0)
    if dead_count > 10:
        findings.append({
            "category": "maintainability",
            "severity": "MEDIUM",
            "title": f"{dead_count} potentially dead functions",
            "detail": "Dead code increases maintenance burden and can confuse developers.",
            "recommendation": "Remove unused functions or mark them with deprecation warnings.",
        })

    # Duplicates
    dupes = arch.get("duplicates", {})
    dupe_groups = dupes.get("groups", 0)
    if dupe_groups > 5:
        findings.append({
            "category": "maintainability",
            "severity": "MEDIUM",
            "title": f"{dupe_groups} duplicate code groups found",
            "detail": "Duplicate code means bugs must be fixed in multiple places.",
            "recommendation": "Extract common logic into shared utilities or base classes.",
        })

    # Architecture patterns
    py_count = file_counts.get(".py", 0)
    js_count = sum(file_counts.get(e, 0) for e in (".js", ".jsx", ".ts", ".tsx"))
    if py_count > 50 and js_count > 20:
        findings.append({
            "category": "architecture",
            "severity": "LOW",
            "title": "Full-stack project detected",
            "detail": f"{py_count} Python files, {js_count} JavaScript/TypeScript files.",
            "recommendation": "Ensure clear API contract between frontend and backend. "
                             "Consider using OpenAPI spec for documentation.",
        })

    if not findings:
        findings.append({
            "category": "overall",
            "severity": "LOW",
            "title": "Project looks healthy",
            "detail": "No major architectural issues detected.",
            "recommendation": "Continue maintaining good practices.",
        })

    return findings


def design_review(directory: str, findings: list | None = None,
                  use_llm: bool = True) -> dict:
    """
    Perform LLM-powered (or rule-based) design review.

    Analyzes:
    - Connectivity health (orphan endpoints, wiring completeness)
    - Code quality (smells, dead code, duplicates)
    - Architecture patterns (separation of concerns, coupling)
    - Suggestions ranked by impact

    Returns design_findings and recommendations.
    """
    root = str(Path(directory).resolve())

    # Build architecture context
    arch = _build_architecture_summary(root)
    file_counts = _count_files(root)

    # Try LLM review first
    llm_review = None
    if use_llm:
        llm_review = _try_llm_review(root, arch, file_counts, findings)

    if llm_review:
        return {
            "source": "llm",
            "findings": llm_review.get("findings", []),
            "architecture_summary": arch,
            "file_counts": file_counts,
            "recommendation": llm_review.get("recommendation", ""),
        }

    # Fallback to rule-based
    rule_findings = _rule_based_review(arch, file_counts)
    return {
        "source": "rule_based",
        "findings": rule_findings,
        "architecture_summary": arch,
        "file_counts": file_counts,
        "recommendation": _overall_recommendation(rule_findings),
    }


def _try_llm_review(directory: str, arch: dict, file_counts: dict,
                     findings: list | None) -> dict | None:
    """Attempt LLM-powered review using available engine."""
    try:
        # Try to use the zen_core LLM engine
        model_path = os.environ.get("ZENAI_MODEL_PATH", "")
        if not model_path:
            models_dir = os.environ.get("SWARM_MODELS_DIR", "")
            if models_dir:
                # Look for a suitable model
                for name in ("qwen2.5-coder-7b-instruct-q4_k_m.gguf",
                              "Qwen2.5-Coder-14B-Instruct-Q4_K_M.gguf"):
                    candidate = os.path.join(models_dir, name)
                    if os.path.isfile(candidate):
                        model_path = candidate
                        break

        if not model_path:
            return None

        from llama_cpp import Llama

        llm = Llama(model_path=model_path, verbose=False,
                     n_gpu_layers=int(os.environ.get("ZENAI_GPU_LAYERS", "-1")),
                     n_ctx=4096, flash_attn=True)

        prompt = _build_review_prompt(arch, file_counts, findings)

        resp = llm.create_chat_completion(
            messages=[
                {"role": "system", "content": (
                    "You are an expert software architect. Analyze the project data and "
                    "return a JSON object with 'findings' (array of {category, severity, "
                    "title, detail, recommendation}) and 'recommendation' (one paragraph). "
                    "Focus on: architecture, coupling, separation of concerns, connectivity, "
                    "and maintainability. Return ONLY valid JSON."
                )},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1500,
            temperature=0.3,
        )

        text = resp["choices"][0]["message"]["content"]
        # Try to parse JSON from response
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(text)

    except Exception:
        return None


def _build_review_prompt(arch: dict, file_counts: dict,
                          findings: list | None) -> str:
    """Build prompt for LLM design review."""
    parts = [
        "Project Architecture Analysis:",
        f"File counts: {json.dumps(file_counts)}",
        f"Connections: {json.dumps(arch.get('connections', {}))}",
        f"Health: {json.dumps(arch.get('health', {}))}",
        f"Code smells: {json.dumps(arch.get('smells', {}))}",
        f"Dead code: {json.dumps(arch.get('dead_code', {}))}",
        f"Duplicates: {json.dumps(arch.get('duplicates', {}))}",
    ]
    if findings:
        severity_counts = {}
        for f in findings:
            sev = f.get("severity", "UNKNOWN") if isinstance(f, dict) else "UNKNOWN"
            severity_counts[sev] = severity_counts.get(sev, 0) + 1
        parts.append(f"Scan findings by severity: {json.dumps(severity_counts)}")

    parts.append("\nAnalyze this architecture and provide findings + recommendations.")
    return "\n".join(parts)


def _overall_recommendation(findings: list[dict]) -> str:
    """Generate overall recommendation from rule-based findings."""
    high = sum(1 for f in findings if f.get("severity") == "HIGH")
    medium = sum(1 for f in findings if f.get("severity") == "MEDIUM")

    if high >= 2:
        return ("Critical architectural issues need attention before new feature work. "
                "Focus on connectivity gaps and health score improvements first.")
    elif medium >= 3:
        return ("Several quality improvements recommended. Schedule a refactoring sprint "
                "to address code smells, dead code, and duplicate logic.")
    else:
        return ("Architecture is in reasonable shape. Continue with incremental improvements "
                "and maintain current practices.")
