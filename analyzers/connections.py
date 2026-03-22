"""
X-Ray LLM — Connection analyzer: map UI actions to backend handlers.
"""

import logging
import re
from collections import defaultdict
from pathlib import Path

from analyzers._shared import _fwd, _walk_ext

# ── Connection Analyzer ──────────────────────────────────────────
_FRONTEND_EXTS = {".js", ".ts", ".jsx", ".tsx", ".html", ".vue", ".svelte"}
_BACKEND_EXTS = {".py", ".js", ".ts"}

# Frontend API-call patterns  (group 1 = URL path)
_FE_PATTERNS = [
    (r"""fetch\(\s*['"`]([^'"`\s]+)['"`]""", "fetch"),
    (r"""axios\.(?:get|post|put|delete|patch)\(\s*['"`]([^'"`\s]+)['"`]""", "axios"),
    (r"""\$\.(?:ajax|get|post)\(\s*['"`]([^'"`\s]+)['"`]""", "jquery"),
    (r"""api\(\s*['"`]([^'"`\s]+)['"`]""", "api"),
    (r"""XMLHttpRequest[^;]*\.open\(\s*['"][^'"]*['"]\s*,\s*['"]([^'"]+)['"]""", "xhr"),
    (r"""action\s*=\s*['"]([^'"]+)['"]""", "form_action"),
    (r"""href\s*=\s*['"](/api/[^'"]+)['"]""", "href"),
]

# Backend route patterns  (group 1 = URL path, or groups vary)
_BE_PATTERNS = [
    # Flask / FastAPI decorators
    (r"""@\w+\.route\(\s*['"]([^'"]+)['"]""", "flask"),
    (r"""@\w+\.(?:get|post|put|delete|patch)\(\s*['"]([^'"]+)['"]""", "fastapi"),
    # Django urlpatterns
    (r"""(?:^|,)\s*path\(\s*['"]([^'"]+)['"]""", "django"),
    (r"""re_path\(\s*['"]([^'"]+)['"]""", "django"),
    # Express
    (r"""(?:app|router)\.(?:get|post|put|delete|patch|all|use)\(\s*['"]([^'"]+)['"]""", "express"),
    # X-Ray custom handler
    (r"""path\s*==\s*['"]([^'"]+)['"]""", "xray_custom"),
]

# HTTP method extraction from nearby context
_METHOD_HINT = re.compile(r"""(?:method|methods)\s*[:=]\s*['"\[]*\s*(GET|POST|PUT|DELETE|PATCH)""", re.I)

# Input-receiving patterns (request data access)
_INPUT_PATTERNS = re.compile(
    r"""(?:request\.(?:json|form|args|data|files|values|get_json|POST|GET|body|query_params)|"""
    r"""req\.(?:body|params|query|file|files)|"""
    r"""self\._read_body\(\))"""
)

# Path parameter normalization: <id>, :id, {id} → _PARAM_
_PARAM_RE = re.compile(r"""(?:<[^>]+>|:\w+|\{[^}]+\})""")


def _normalize_route(url: str) -> str:
    """Normalize a URL for matching: strip qs, trailing slash, unify path params."""
    url = url.split("?")[0].rstrip("/") or "/"
    return _PARAM_RE.sub("_PARAM_", url)


def _is_relative_api(url: str) -> bool:
    """Return True if URL looks like a relative API path (not external)."""
    if url.startswith(("http://", "https://", "//")):
        return False
    return url.startswith("/")


def _infer_method(context: str, call_type: str) -> str:
    """Infer HTTP method from surrounding code context."""
    m = _METHOD_HINT.search(context)
    if m:
        return m.group(1).upper()
    if call_type in ("form_action",):
        return "POST"
    if "post" in call_type.lower():
        return "POST"
    return "UNKNOWN"


def _extract_function_body(content: str, line_idx: int) -> str:
    """Extract a rough function body (next 30 lines) for input-pattern detection."""
    lines = content.splitlines()
    end = min(line_idx + 30, len(lines))
    return "\n".join(lines[line_idx:end])


def analyze_connections(directory: str) -> dict:
    """Static analysis: map UI actions to backend handlers, detect orphans and cardinality."""
    ui_actions = []  # {"file", "line", "call_type", "url", "method"}
    handlers = []  # {"file", "line", "route", "method", "framework", "receives_input"}
    frameworks = set()

    # ── Phase A: Parse frontend files for API calls ──
    compiled_fe = [(re.compile(p, re.MULTILINE), ct) for p, ct in _FE_PATTERNS]

    for fpath, rel in _walk_ext(directory, _FRONTEND_EXTS):
        try:
            content = Path(fpath).read_text(encoding="utf-8", errors="ignore")
        except OSError as e:
            logging.debug("Skipped frontend API scan for %s: %s", fpath, e)
            continue
        for pat, call_type in compiled_fe:
            for m in pat.finditer(content):
                url = m.group(1)
                if not _is_relative_api(url):
                    continue
                line = content[: m.start()].count("\n") + 1
                ctx = content[max(0, m.start() - 100) : m.end() + 100]
                ui_actions.append(
                    {
                        "file": _fwd(rel),
                        "line": line,
                        "call_type": call_type,
                        "url": url.split("?")[0],
                        "method": _infer_method(ctx, call_type),
                    }
                )

    # ── Phase B: Parse backend files for route handlers ──
    compiled_be = [(re.compile(p, re.MULTILINE), fw) for p, fw in _BE_PATTERNS]

    for fpath, rel in _walk_ext(directory, _BACKEND_EXTS):
        try:
            content = Path(fpath).read_text(encoding="utf-8", errors="ignore")
        except OSError as e:
            logging.debug("Skipped backend API scan for %s: %s", fpath, e)
            continue
        for pat, framework in compiled_be:
            for m in pat.finditer(content):
                route = m.group(1)
                if not route.startswith("/"):
                    route = "/" + route
                line = content[: m.start()].count("\n") + 1
                frameworks.add(framework)

                # Infer HTTP method
                ctx = content[max(0, m.start() - 60) : m.end() + 60]
                method_match = re.search(r"""\.(?:get|post|put|delete|patch)\(""", ctx, re.I)
                if method_match:
                    method = method_match.group(0).split(".")[1].split("(")[0].upper()
                else:
                    hint = _METHOD_HINT.search(ctx)
                    method = hint.group(1).upper() if hint else "ANY"

                # Check if handler body receives input
                body_text = _extract_function_body(content, line)
                receives_input = bool(_INPUT_PATTERNS.search(body_text))

                handlers.append(
                    {
                        "file": _fwd(rel),
                        "line": line,
                        "route": route,
                        "method": method,
                        "framework": framework,
                        "receives_input": receives_input,
                    }
                )

    # ── Phase C: Build connection map ──
    # Group by normalized path
    ui_by_path = defaultdict(list)
    for a in ui_actions:
        ui_by_path[_normalize_route(a["url"])].append(a)

    be_by_path = defaultdict(list)
    for h in handlers:
        be_by_path[_normalize_route(h["route"])].append(h)

    all_paths = set(ui_by_path.keys()) | set(be_by_path.keys())

    wired = []
    orphan_ui = []
    orphan_backend = []
    card_counts = {"1:1": 0, "1:many": 0, "many:1": 0}

    for path in sorted(all_paths):
        ui_list = ui_by_path.get(path, [])
        be_list = be_by_path.get(path, [])

        if ui_list and be_list:
            # Determine cardinality
            n_ui, n_be = len(ui_list), len(be_list)
            if n_ui == 1 and n_be == 1:
                cardinality = "1:1"
            elif n_ui > 1:
                cardinality = "many:1"
            else:
                cardinality = "1:many"
            card_counts[cardinality] += 1
            wired.append(
                {
                    "url": ui_list[0]["url"],
                    "cardinality": cardinality,
                    "ui_actions": ui_list[:20],
                    "handlers": be_list[:20],
                }
            )
        elif ui_list and not be_list:
            orphan_ui.extend(ui_list[:20])
        elif be_list and not ui_list:
            orphan_backend.extend(be_list[:20])

    # Cap results
    wired = wired[:500]
    orphan_ui = orphan_ui[:500]
    orphan_backend = orphan_backend[:500]

    return {
        "wired": wired,
        "orphan_ui": orphan_ui,
        "orphan_backend": orphan_backend,
        "summary": {
            "total_ui_actions": len(ui_actions),
            "total_handlers": len(handlers),
            "wired_count": len(wired),
            "orphan_ui_count": len(orphan_ui),
            "orphan_backend_count": len(orphan_backend),
            "cardinality": card_counts,
        },
        "frameworks_detected": sorted(frameworks),
    }
