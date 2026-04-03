"""
Bidirectional Orphan Map — First-class orphan audit for UI ↔ Backend connectivity.
Extends the basic connection analysis with:
  - WebSocket event orphans
  - Route parameter mismatches
  - Mermaid diagram generation
  - Detailed orphan classification
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

from analyzers._shared import _SKIP_DIRS, _WEB_EXTS, _PY_EXTS


# ── Data Classes ──────────────────────────────────────────────────────

@dataclass
class OrphanEntry:
    kind: str           # "frontend" | "backend" | "websocket_emit" | "websocket_listen"
    url: str
    method: str         # GET/POST/PUT/DELETE/PATCH or "WS"
    file: str
    line: int
    context: str = ""   # surrounding code snippet
    severity: str = "MEDIUM"

@dataclass
class ParamMismatch:
    url: str
    frontend_params: list[str]
    backend_params: list[str]
    frontend_file: str
    backend_file: str
    frontend_line: int
    backend_line: int

@dataclass
class OrphanMapResult:
    orphan_frontend: list[OrphanEntry] = field(default_factory=list)
    orphan_backend: list[OrphanEntry] = field(default_factory=list)
    ws_emit_orphans: list[OrphanEntry] = field(default_factory=list)
    ws_listen_orphans: list[OrphanEntry] = field(default_factory=list)
    param_mismatches: list[ParamMismatch] = field(default_factory=list)
    wired: list[dict] = field(default_factory=list)
    mermaid: str = ""
    summary: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "orphan_frontend": [asdict(o) for o in self.orphan_frontend],
            "orphan_backend": [asdict(o) for o in self.orphan_backend],
            "ws_emit_orphans": [asdict(o) for o in self.ws_emit_orphans],
            "ws_listen_orphans": [asdict(o) for o in self.ws_listen_orphans],
            "param_mismatches": [asdict(m) for m in self.param_mismatches],
            "wired": self.wired,
            "mermaid": self.mermaid,
            "summary": self.summary,
        }


# ── Regex Patterns ────────────────────────────────────────────────────

# Frontend API calls
_FE_FETCH = re.compile(
    r"""(?:fetch|axios\.(?:get|post|put|delete|patch)|api\s*\(|"""
    r"""\$\.(?:ajax|get|post)|XMLHttpRequest)\s*\(\s*"""
    r"""[`'"](/?(?:api|v\d+)?/[^'"`\s]+)[`'"]""",
    re.IGNORECASE,
)
_FE_FORM_ACTION = re.compile(r"""<form[^>]*action\s*=\s*['"](/?api/[^'"]+)['"]""", re.IGNORECASE)

# Backend route declarations
_BE_DECORATOR = re.compile(
    r"""@(?:app|router|blueprint)\s*\.\s*(?:route|get|post|put|delete|patch)\s*\(\s*['"](/?[^'"]+)['"]"""
)
_BE_PATH_EQ = re.compile(r"""path\s*==\s*['"](/?api/[^'"]+)['"]""")
_BE_EXPRESS = re.compile(
    r"""(?:app|router)\s*\.\s*(get|post|put|delete|patch)\s*\(\s*['"](/?[^'"]+)['"]"""
)

# WebSocket events
_WS_EMIT = re.compile(r"""(?:socket|ws|io)\s*\.\s*emit\s*\(\s*['"]([^'"]+)['"]""", re.IGNORECASE)
_WS_ON = re.compile(r"""(?:socket|ws|io)\s*\.\s*on\s*\(\s*['"]([^'"]+)['"]""", re.IGNORECASE)

# Route parameters
_PARAM_PY = re.compile(r"<(\w+)(?::\w+)?>")      # Flask <id>, <int:id>
_PARAM_EXPRESS = re.compile(r":(\w+)")              # Express :id
_PARAM_FASTAPI = re.compile(r"\{(\w+)\}")           # FastAPI {id}
_PARAM_JS = re.compile(r"\$\{(\w+)\}|/(\w+)(?=/|$)")  # Template literal


def _normalize_path(p: str) -> str:
    """Normalize route path for comparison."""
    p = p.rstrip("/").split("?")[0]
    p = _PARAM_PY.sub("_PARAM_", p)
    p = _PARAM_EXPRESS.sub("_PARAM_", p)
    p = _PARAM_FASTAPI.sub("_PARAM_", p)
    return p.lower()


def _extract_params(route: str) -> list[str]:
    """Extract named parameters from a route pattern."""
    params = []
    for rx in (_PARAM_PY, _PARAM_EXPRESS, _PARAM_FASTAPI):
        params.extend(rx.findall(route))
    # Flatten tuples from _PARAM_JS
    for m in _PARAM_JS.finditer(route):
        params.extend(g for g in m.groups() if g)
    return [p for p in params if p]


def _should_skip(dirpath: str) -> bool:
    parts = Path(dirpath).parts
    return any(p in _SKIP_DIRS or p.startswith((".venv", "venv", "__pycache__", "node_modules"))
               for p in parts)


def _walk_files(root: str, exts: set[str]):
    """Walk directory yielding (filepath, ext) for given extensions."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not _should_skip(os.path.join(dirpath, d))]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext in exts:
                yield os.path.join(dirpath, fn), ext


# ── Main Analysis ─────────────────────────────────────────────────────

def analyze_orphan_map(directory: str) -> dict:
    """
    Perform bidirectional orphan analysis:
    1. Scan frontend files for API calls and WS events
    2. Scan backend files for route declarations and WS handlers
    3. Match and detect orphans in both directions
    4. Detect parameter naming mismatches
    5. Generate Mermaid connectivity diagram
    """
    root = str(Path(directory).resolve())
    result = OrphanMapResult()

    fe_calls: list[dict] = []   # {url, method, file, line, raw, params}
    be_routes: list[dict] = []  # {url, method, file, line, raw, params}
    ws_emits: list[dict] = []   # {event, file, line}
    ws_listeners: list[dict] = []  # {event, file, line}

    fe_exts = {".js", ".jsx", ".ts", ".tsx", ".html", ".vue", ".svelte"}
    be_exts = {".py", ".js", ".ts"}

    # ── Phase 1: Scan Frontend ────────────────────────────────────────
    for fp, ext in _walk_files(root, fe_exts):
        try:
            with open(fp, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError:
            continue

        rel = os.path.relpath(fp, root)
        for i, line in enumerate(lines, 1):
            for m in _FE_FETCH.finditer(line):
                url = m.group(1)
                fe_calls.append({
                    "url": url, "norm": _normalize_path(url),
                    "method": "POST" if "post" in m.group(0).lower() else "GET",
                    "file": rel, "line": i, "raw": url,
                    "params": _extract_params(url),
                })
            for m in _FE_FORM_ACTION.finditer(line):
                url = m.group(1)
                fe_calls.append({
                    "url": url, "norm": _normalize_path(url),
                    "method": "POST", "file": rel, "line": i,
                    "raw": url, "params": _extract_params(url),
                })
            for m in _WS_EMIT.finditer(line):
                ws_emits.append({"event": m.group(1), "file": rel, "line": i})
            for m in _WS_ON.finditer(line):
                ws_listeners.append({"event": m.group(1), "file": rel, "line": i})

    # ── Phase 2: Scan Backend ─────────────────────────────────────────
    for fp, ext in _walk_files(root, be_exts):
        # Skip frontend dirs when scanning backend
        rel = os.path.relpath(fp, root)
        if any(d in rel for d in ("node_modules", "dist", "build", ".next")):
            continue
        try:
            with open(fp, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError:
            continue

        for i, line in enumerate(lines, 1):
            for rx in (_BE_DECORATOR, _BE_PATH_EQ):
                for m in rx.finditer(line):
                    url = m.group(1)
                    method = "GET"
                    if ".post(" in line.lower():
                        method = "POST"
                    elif ".put(" in line.lower():
                        method = "PUT"
                    elif ".delete(" in line.lower():
                        method = "DELETE"
                    be_routes.append({
                        "url": url, "norm": _normalize_path(url),
                        "method": method, "file": rel, "line": i,
                        "raw": url, "params": _extract_params(url),
                    })
            for m in _BE_EXPRESS.finditer(line):
                method = m.group(1).upper()
                url = m.group(2)
                be_routes.append({
                    "url": url, "norm": _normalize_path(url),
                    "method": method, "file": rel, "line": i,
                    "raw": url, "params": _extract_params(url),
                })
            for m in _WS_ON.finditer(line):
                if ext == ".py":
                    ws_listeners.append({"event": m.group(1), "file": rel, "line": i})
            for m in _WS_EMIT.finditer(line):
                if ext == ".py":
                    ws_emits.append({"event": m.group(1), "file": rel, "line": i})

    # ── Phase 3: Match & Detect Orphans ───────────────────────────────
    fe_norms = {c["norm"] for c in fe_calls}
    be_norms = {r["norm"] for r in be_routes}

    # Build lookup maps
    be_by_norm: dict[str, list[dict]] = {}
    for r in be_routes:
        be_by_norm.setdefault(r["norm"], []).append(r)
    fe_by_norm: dict[str, list[dict]] = {}
    for c in fe_calls:
        fe_by_norm.setdefault(c["norm"], []).append(c)

    # Wired connections
    wired_norms = fe_norms & be_norms
    for norm in sorted(wired_norms):
        result.wired.append({
            "url": norm,
            "frontend_calls": fe_by_norm[norm][:10],
            "backend_handlers": be_by_norm[norm][:10],
        })

    # Frontend orphans (call with no backend)
    for norm in sorted(fe_norms - be_norms):
        for c in fe_by_norm[norm][:5]:
            result.orphan_frontend.append(OrphanEntry(
                kind="frontend", url=c["raw"], method=c["method"],
                file=c["file"], line=c["line"],
                severity="HIGH" if c["method"] in ("POST", "PUT", "DELETE") else "MEDIUM",
            ))

    # Backend orphans (handler with no frontend call)
    for norm in sorted(be_norms - fe_norms):
        for r in be_by_norm[norm][:5]:
            result.orphan_backend.append(OrphanEntry(
                kind="backend", url=r["raw"], method=r["method"],
                file=r["file"], line=r["line"], severity="LOW",
            ))

    # ── Phase 4: WebSocket Orphans ────────────────────────────────────
    emit_events = {e["event"] for e in ws_emits}
    listen_events = {e["event"] for e in ws_listeners}

    for e in ws_emits:
        if e["event"] not in listen_events:
            result.ws_emit_orphans.append(OrphanEntry(
                kind="websocket_emit", url=e["event"], method="WS",
                file=e["file"], line=e["line"], severity="MEDIUM",
            ))
    for e in ws_listeners:
        if e["event"] not in emit_events:
            result.ws_listen_orphans.append(OrphanEntry(
                kind="websocket_listen", url=e["event"], method="WS",
                file=e["file"], line=e["line"], severity="MEDIUM",
            ))

    # ── Phase 5: Parameter Mismatches ─────────────────────────────────
    for norm in wired_norms:
        fe_params_sets = [set(c["params"]) for c in fe_by_norm[norm] if c["params"]]
        be_params_sets = [set(r["params"]) for r in be_by_norm[norm] if r["params"]]
        if fe_params_sets and be_params_sets:
            fe_p = fe_params_sets[0]
            be_p = be_params_sets[0]
            if fe_p != be_p and fe_p and be_p:
                result.param_mismatches.append(ParamMismatch(
                    url=norm,
                    frontend_params=sorted(fe_p),
                    backend_params=sorted(be_p),
                    frontend_file=fe_by_norm[norm][0]["file"],
                    backend_file=be_by_norm[norm][0]["file"],
                    frontend_line=fe_by_norm[norm][0]["line"],
                    backend_line=be_by_norm[norm][0]["line"],
                ))

    # ── Phase 6: Mermaid Diagram ──────────────────────────────────────
    mermaid_lines = ["graph LR"]
    for w in result.wired[:30]:
        url_label = w["url"].replace("/", "_").replace("-", "_").strip("_") or "root"
        fe_f = w["frontend_calls"][0]["file"] if w["frontend_calls"] else "UI"
        be_f = w["backend_handlers"][0]["file"] if w["backend_handlers"] else "API"
        mermaid_lines.append(f'    {_safe_id(fe_f)}["{fe_f}"] -->|{w["url"]}| {_safe_id(be_f)}["{be_f}"]')

    for o in result.orphan_frontend[:15]:
        mermaid_lines.append(f'    {_safe_id(o.file)}["{o.file}"] -.->|"{o.url}"| MISSING_BACKEND["❌ No Handler"]')
    for o in result.orphan_backend[:15]:
        mermaid_lines.append(f'    MISSING_FRONTEND["❌ No Caller"] -.->|"{o.url}"| {_safe_id(o.file)}["{o.file}"]')

    result.mermaid = "\n".join(mermaid_lines)

    # ── Summary ───────────────────────────────────────────────────────
    result.summary = {
        "total_frontend_calls": len(fe_calls),
        "total_backend_routes": len(be_routes),
        "wired_count": len(result.wired),
        "orphan_frontend_count": len(result.orphan_frontend),
        "orphan_backend_count": len(result.orphan_backend),
        "ws_emit_orphans": len(result.ws_emit_orphans),
        "ws_listen_orphans": len(result.ws_listen_orphans),
        "param_mismatches": len(result.param_mismatches),
        "ws_events_total": len(emit_events | listen_events),
        "connectivity_score": _connectivity_score(
            len(result.wired),
            len(result.orphan_frontend),
            len(result.orphan_backend),
        ),
    }

    return result.to_dict()


def _safe_id(s: str) -> str:
    """Make a string safe for Mermaid node IDs."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", s)[:40]


def _connectivity_score(wired: int, orphan_fe: int, orphan_be: int) -> int:
    """0-100 score: 100 = everything wired, 0 = nothing connected."""
    total = wired + orphan_fe + orphan_be
    if total == 0:
        return 100
    return max(0, min(100, int(100 * wired / total)))
