"""
Schema / Contract Drift Detection — Detects mismatches between
backend models (Pydantic, dataclass, TypedDict) and frontend request/response usage.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

from analyzers._shared import _SKIP_DIRS


# ── Backend Model Extraction ──────────────────────────────────────────

def _extract_pydantic_models(directory: str) -> list[dict]:
    """Extract Pydantic model definitions with their fields."""
    models = []
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = [d for d in dirnames
                       if d not in _SKIP_DIRS and not d.startswith((".venv", "node_modules"))]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            fp = os.path.join(dirpath, fn)
            try:
                with open(fp, encoding="utf-8", errors="replace") as f:
                    source = f.read()
                tree = ast.parse(source, filename=fp)
            except (OSError, SyntaxError):
                continue

            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                # Check if it inherits from BaseModel, Schema, or TypedDict
                base_names = []
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        base_names.append(base.id)
                    elif isinstance(base, ast.Attribute):
                        base_names.append(base.attr)

                is_model = any(b in ("BaseModel", "Schema", "TypedDict", "SQLModel")
                               for b in base_names)
                if not is_model:
                    continue

                fields = {}
                for child in node.body:
                    if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                        field_name = child.target.id
                        field_type = _get_annotation_str(child.annotation)
                        fields[field_name] = field_type

                if fields:
                    models.append({
                        "name": node.name,
                        "fields": fields,
                        "file": os.path.relpath(fp, directory),
                        "line": node.lineno,
                        "base": base_names[0] if base_names else "unknown",
                    })
    return models


def _get_annotation_str(node: ast.expr) -> str:
    """Convert AST annotation to string representation."""
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Constant):
        return str(node.value)
    elif isinstance(node, ast.Attribute):
        return f"{_get_annotation_str(node.value)}.{node.attr}"
    elif isinstance(node, ast.Subscript):
        return f"{_get_annotation_str(node.value)}[{_get_annotation_str(node.slice)}]"
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return f"{_get_annotation_str(node.left)} | {_get_annotation_str(node.right)}"
    elif isinstance(node, ast.Tuple):
        return ", ".join(_get_annotation_str(e) for e in node.elts)
    return "Any"


# ── Frontend Field Usage Extraction ───────────────────────────────────

_FE_FIELD_ACCESS = re.compile(
    r"""(?:data|response|result|res|json|body|payload|item|row|record)"""
    r"""(?:\.\s*(\w+)|\[\s*['"]([\w]+)['"]\s*\])"""
)
_FE_SEND_FIELD = re.compile(
    r"""['"]([\w]+)['"]\s*:"""
)
_FE_DESTRUCTURE = re.compile(
    r"""(?:const|let|var)\s+\{([^}]+)\}\s*=\s*(?:data|response|result|res|await|props)"""
)


def _extract_frontend_fields(directory: str) -> dict:
    """Extract field names used in frontend API interactions."""
    read_fields: dict[str, set] = {}   # url -> {fields read from response}
    send_fields: dict[str, set] = {}   # url -> {fields sent in request}

    url_context_rx = re.compile(
        r"""(?:fetch|axios\.\w+|api)\s*\(\s*[`'"](/[^'"`\s]+)[`'"]"""
    )

    fe_exts = {".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte"}
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = [d for d in dirnames
                       if d not in _SKIP_DIRS and not d.startswith((".venv", "node_modules"))]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in fe_exts:
                continue
            fp = os.path.join(dirpath, fn)
            try:
                with open(fp, encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except OSError:
                continue

            # Find API call contexts
            lines = content.splitlines()
            for i, line in enumerate(lines):
                url_match = url_context_rx.search(line)
                if not url_match:
                    continue
                url = url_match.group(1)

                # Look at surrounding context (±15 lines)
                ctx = "\n".join(lines[max(0, i - 5):min(len(lines), i + 15)])

                # Fields read from response
                for m in _FE_FIELD_ACCESS.finditer(ctx):
                    field = m.group(1) or m.group(2)
                    if field and len(field) > 1:
                        read_fields.setdefault(url, set()).add(field)

                # Destructured fields
                for m in _FE_DESTRUCTURE.finditer(ctx):
                    for f in m.group(1).split(","):
                        f = f.strip().split(":")[0].strip().split("=")[0].strip()
                        if f and len(f) > 1:
                            read_fields.setdefault(url, set()).add(f)

                # Fields sent in request body
                for m in _FE_SEND_FIELD.finditer(ctx):
                    field = m.group(1)
                    if field and len(field) > 1:
                        send_fields.setdefault(url, set()).add(field)

    return {
        "read_fields": {k: sorted(v) for k, v in read_fields.items()},
        "send_fields": {k: sorted(v) for k, v in send_fields.items()},
    }


# ── Endpoint to Model Mapping ────────────────────────────────────────

def _map_endpoints_to_models(directory: str, models: list[dict]) -> dict[str, list[str]]:
    """Map API endpoints to the model names they use (via type hints and return types)."""
    mapping: dict[str, list[str]] = {}
    model_names = {m["name"] for m in models}
    route_rx = re.compile(r"""@\w+\.\s*(?:route|get|post|put|delete|patch)\s*\(\s*['"]([^'"]+)['"]""")

    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = [d for d in dirnames
                       if d not in _SKIP_DIRS and not d.startswith((".venv", "node_modules"))]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            fp = os.path.join(dirpath, fn)
            try:
                with open(fp, encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except OSError:
                continue

            lines = content.splitlines()
            for i, line in enumerate(lines):
                m = route_rx.search(line)
                if not m:
                    continue
                url = m.group(1)
                # Look at handler function (next ~30 lines)
                ctx = "\n".join(lines[i:min(len(lines), i + 30)])
                found_models = [name for name in model_names if name in ctx]
                if found_models:
                    mapping[url] = found_models

    return mapping


# ── Main Analysis ─────────────────────────────────────────────────────

def detect_schema_drift(directory: str) -> dict:
    """
    Detect schema/contract drift between backend models and frontend usage.

    Returns:
    - models: all Pydantic/TypedDict models found
    - drift: mismatches between model fields and frontend usage
    - unused_fields: model fields never used by frontend
    - missing_fields: fields frontend expects but model doesn't have
    """
    root = str(Path(directory).resolve())

    models = _extract_pydantic_models(root)
    fe_usage = _extract_frontend_fields(root)
    endpoint_models = _map_endpoints_to_models(root, models)

    model_by_name = {m["name"]: m for m in models}
    drifts: list[dict] = []
    unused_fields: list[dict] = []
    missing_fields: list[dict] = []

    # Compare frontend field usage against model definitions
    for url, model_names in endpoint_models.items():
        fe_read = set(fe_usage.get("read_fields", {}).get(url, []))
        fe_send = set(fe_usage.get("send_fields", {}).get(url, []))
        fe_all = fe_read | fe_send

        for model_name in model_names:
            model = model_by_name.get(model_name)
            if not model:
                continue

            model_fields = set(model["fields"].keys())

            # Fields in model but never used by frontend
            for f in sorted(model_fields - fe_all):
                if not f.startswith("_"):
                    unused_fields.append({
                        "model": model_name,
                        "field": f,
                        "field_type": model["fields"][f],
                        "url": url,
                        "model_file": model["file"],
                        "model_line": model["line"],
                        "severity": "LOW",
                    })

            # Fields frontend expects but model doesn't have
            for f in sorted(fe_all - model_fields):
                missing_fields.append({
                    "model": model_name,
                    "field": f,
                    "url": url,
                    "model_file": model["file"],
                    "severity": "HIGH",
                    "description": f"Frontend expects field '{f}' but {model_name} has no such field",
                })

    # Build drift entries from missing fields
    for mf in missing_fields:
        drifts.append({
            "type": "missing_field",
            **mf,
        })
    for uf in unused_fields:
        drifts.append({
            "type": "unused_field",
            **uf,
        })

    return {
        "models": [{**m, "fields": dict(m["fields"])} for m in models],
        "drift": drifts,
        "unused_fields": unused_fields,
        "missing_fields": missing_fields,
        "frontend_usage": {
            "read_fields": fe_usage.get("read_fields", {}),
            "send_fields": fe_usage.get("send_fields", {}),
        },
        "endpoint_model_map": endpoint_models,
        "summary": {
            "total_models": len(models),
            "total_drift_issues": len(drifts),
            "missing_field_count": len(missing_fields),
            "unused_field_count": len(unused_fields),
            "endpoints_with_models": len(endpoint_models),
        },
    }
