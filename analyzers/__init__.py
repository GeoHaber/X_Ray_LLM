"""
X-Ray LLM — Extended Analyzers
================================
Ported and adapted from old X_Ray Analysis/ modules.
Provides: code smells, dead functions, duplicate detection, security (bandit + secrets),
project health, format checking, temporal coupling, release readiness, coverage zones,
AI code detection, web smells, and test generation stubs.
"""

# ── Shared constants & helpers ──
from analyzers._shared import (
    _PY_EXTS,
    _SKIP_DIRS,
    _TEXT_EXTS,
    _WEB_EXTS,
    _fwd,
    _safe_parse,
    _walk_ext,
    _walk_py,
)

# ── Connections ──
from analyzers.connections import (
    _extract_function_body,
    _infer_method,
    _is_relative_api,
    _normalize_route,
    analyze_connections,
)

# ── Detection (AI code, web smells, test stubs) ──
from analyzers.detection import (
    detect_ai_code,
    detect_web_smells,
    generate_test_stubs,
)

# ── Format checking & type checking ──
from analyzers.format_check import (
    check_format,
    check_types,
    run_typecheck,
)

# ── Graph analysis ──
from analyzers.graph import (
    compute_coupling_metrics,
    detect_circular_calls,
    detect_unused_imports,
)

# ── Health & readiness ──
from analyzers.health import (
    check_project_health,
    check_release_readiness,
    estimate_remediation_time,
)

# ── PM Dashboard ──
from analyzers.pm_dashboard import (
    compute_architecture_map,
    compute_call_graph,
    compute_confidence_meter,
    compute_module_cards,
    compute_project_review,
    compute_risk_heatmap,
    compute_sprint_batches,
)

# ── Security ──
from analyzers.security import run_bandit

# ── Smells & duplicates ──
from analyzers.smells import (
    _max_nesting,
    detect_code_smells,
    detect_dead_functions,
    detect_duplicates,
)

# ── Temporal coupling ──
from analyzers.temporal import analyze_temporal_coupling

__all__ = [
    "_PY_EXTS",
    # Shared
    "_SKIP_DIRS",
    "_TEXT_EXTS",
    "_WEB_EXTS",
    "_extract_function_body",
    "_fwd",
    "_infer_method",
    "_is_relative_api",
    "_max_nesting",
    "_normalize_route",
    "_safe_parse",
    "_walk_ext",
    "_walk_py",
    # Connections
    "analyze_connections",
    # Temporal
    "analyze_temporal_coupling",
    # Format / types
    "check_format",
    # Health
    "check_project_health",
    "check_release_readiness",
    "check_types",
    "compute_architecture_map",
    "compute_call_graph",
    "compute_confidence_meter",
    "compute_coupling_metrics",
    "compute_module_cards",
    "compute_project_review",
    # PM Dashboard
    "compute_risk_heatmap",
    "compute_sprint_batches",
    # Detection
    "detect_ai_code",
    # Graph
    "detect_circular_calls",
    "detect_code_smells",
    # Smells
    "detect_dead_functions",
    "detect_duplicates",
    "detect_unused_imports",
    "detect_web_smells",
    "estimate_remediation_time",
    "generate_test_stubs",
    # Security
    "run_bandit",
    "run_typecheck",
]
