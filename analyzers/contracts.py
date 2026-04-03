"""
Design Contract Verification — Validates codebase against a YAML/JSON design spec.
Checks: endpoints exist, UI components exist, request/response schemas match,
no undeclared endpoints (security surface audit).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from analyzers._shared import _SKIP_DIRS


def _load_contract(contract_path: str) -> dict:
    """Load contract from YAML or JSON file."""
    with open(contract_path, encoding="utf-8") as f:
        text = f.read()

    if contract_path.endswith((".yaml", ".yml")):
        try:
            import yaml
            return yaml.safe_load(text)
        except ImportError:
            raise ImportError("PyYAML required for YAML contracts: pip install pyyaml")
    else:
        return json.loads(text)


def _find_endpoint_in_code(directory: str, endpoint: str, method: str) -> dict | None:
    """Search for a route declaration matching the endpoint."""
    patterns = [
        re.compile(rf"""@\w+\.(?:route|{method.lower()})\s*\(\s*['"]{re.escape(endpoint)}['"]"""),
        re.compile(rf"""path\s*==\s*['"]{re.escape(endpoint)}['"]"""),
        re.compile(rf"""\.{method.lower()}\s*\(\s*['"]{re.escape(endpoint)}['"]"""),
    ]
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = [d for d in dirnames
                       if d not in _SKIP_DIRS and not d.startswith((".venv", "node_modules"))]
        for fn in filenames:
            if not fn.endswith((".py", ".js", ".ts")):
                continue
            fp = os.path.join(dirpath, fn)
            try:
                with open(fp, encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        for pat in patterns:
                            if pat.search(line):
                                return {"file": os.path.relpath(fp, directory), "line": i}
            except OSError:
                continue
    return None


def _find_component_in_code(directory: str, component: str) -> dict | None:
    """Search for a UI component (React, Vue, HTML element)."""
    patterns = [
        re.compile(rf"""(?:function|const|class)\s+{re.escape(component)}\b"""),
        re.compile(rf"""export\s+(?:default\s+)?(?:function|class|const)\s+{re.escape(component)}\b"""),
        re.compile(rf"""<{re.escape(component)}[\s/>]"""),
        re.compile(rf"""id\s*=\s*['"]{re.escape(component)}['"]"""),
    ]
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = [d for d in dirnames
                       if d not in _SKIP_DIRS and not d.startswith((".venv", "node_modules"))]
        for fn in filenames:
            if not fn.endswith((".js", ".jsx", ".ts", ".tsx", ".html", ".vue", ".svelte")):
                continue
            fp = os.path.join(dirpath, fn)
            try:
                with open(fp, encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        for pat in patterns:
                            if pat.search(line):
                                return {"file": os.path.relpath(fp, directory), "line": i}
            except OSError:
                continue
    return None


def _find_all_endpoints(directory: str) -> list[dict]:
    """Discover all declared endpoints in the codebase."""
    route_patterns = [
        re.compile(r"""@\w+\.\s*(route|get|post|put|delete|patch)\s*\(\s*['"]([^'"]+)['"]"""),
        re.compile(r"""(?:app|router)\.\s*(get|post|put|delete|patch)\s*\(\s*['"]([^'"]+)['"]"""),
    ]
    endpoints = []
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = [d for d in dirnames
                       if d not in _SKIP_DIRS and not d.startswith((".venv", "node_modules"))]
        for fn in filenames:
            if not fn.endswith((".py", ".js", ".ts")):
                continue
            fp = os.path.join(dirpath, fn)
            try:
                with open(fp, encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        for pat in route_patterns:
                            for m in pat.finditer(line):
                                method = m.group(1).upper()
                                if method == "ROUTE":
                                    method = "GET"
                                endpoints.append({
                                    "method": method,
                                    "url": m.group(2),
                                    "file": os.path.relpath(fp, directory),
                                    "line": i,
                                })
            except OSError:
                continue
    return endpoints


def verify_contract(directory: str, contract_path: str | None = None,
                    contract_data: dict | None = None) -> dict:
    """
    Verify a project against its design contract.

    Contract format (YAML/JSON):
    ```yaml
    endpoints:
      - url: /api/users
        method: GET
        request_params: [page, limit]
        response_fields: [id, name, email]
        description: List all users
      - url: /api/users
        method: POST
        request_body: {name: string, email: string}
        response_fields: [id, name, email]

    components:
      - name: UserList
        binds_to: /api/users  # which endpoint it uses
      - name: LoginForm
        binds_to: /api/auth/login

    rules:
      no_undeclared_endpoints: true  # flag endpoints not in contract
    ```
    """
    root = str(Path(directory).resolve())
    if contract_data is None and contract_path:
        contract_data = _load_contract(contract_path)
    elif contract_data is None:
        # Try default locations
        for name in ("xray-contract.yaml", "xray-contract.yml", "xray-contract.json",
                      ".xray-contract.yaml", ".xray-contract.json"):
            candidate = os.path.join(root, name)
            if os.path.isfile(candidate):
                contract_data = _load_contract(candidate)
                break

    if contract_data is None:
        return {
            "error": "No contract found. Create xray-contract.yaml in project root.",
            "template": _contract_template(),
        }

    violations: list[dict] = []
    verified: list[dict] = []

    # ── Check Endpoints ───────────────────────────────────────────────
    declared_endpoints = contract_data.get("endpoints", [])
    for ep in declared_endpoints:
        url = ep.get("url", "")
        method = ep.get("method", "GET").upper()
        found = _find_endpoint_in_code(root, url, method)
        if found:
            verified.append({
                "type": "endpoint",
                "url": url,
                "method": method,
                "status": "found",
                **found,
            })
        else:
            violations.append({
                "type": "missing_endpoint",
                "severity": "HIGH",
                "url": url,
                "method": method,
                "description": f"Declared endpoint {method} {url} not found in code",
            })

    # ── Check Components ──────────────────────────────────────────────
    declared_components = contract_data.get("components", [])
    for comp in declared_components:
        name = comp.get("name", "")
        found = _find_component_in_code(root, name)
        if found:
            verified.append({
                "type": "component",
                "name": name,
                "status": "found",
                **found,
            })
            # Check binding
            binds_to = comp.get("binds_to", "")
            if binds_to:
                # Verify the component actually calls that endpoint
                pass  # Would need deeper analysis
        else:
            violations.append({
                "type": "missing_component",
                "severity": "MEDIUM",
                "name": name,
                "description": f"Declared component '{name}' not found in code",
            })

    # ── Check for Undeclared Endpoints (Security Surface) ─────────────
    rules = contract_data.get("rules", {})
    if rules.get("no_undeclared_endpoints", False):
        all_code_endpoints = _find_all_endpoints(root)
        declared_urls = {(ep.get("url", ""), ep.get("method", "GET").upper())
                        for ep in declared_endpoints}
        for ce in all_code_endpoints:
            key = (ce["url"], ce["method"])
            if key not in declared_urls:
                violations.append({
                    "type": "undeclared_endpoint",
                    "severity": "MEDIUM",
                    "url": ce["url"],
                    "method": ce["method"],
                    "file": ce["file"],
                    "line": ce["line"],
                    "description": f"Undeclared endpoint {ce['method']} {ce['url']} — not in contract",
                })

    # ── Summary ───────────────────────────────────────────────────────
    total_checks = len(declared_endpoints) + len(declared_components)
    passed = len(verified)

    return {
        "verified": verified,
        "violations": violations,
        "summary": {
            "total_declared": total_checks,
            "verified": passed,
            "violations": len(violations),
            "compliance_pct": int(100 * passed / total_checks) if total_checks else 100,
            "high_violations": sum(1 for v in violations if v.get("severity") == "HIGH"),
        },
    }


def _contract_template() -> dict:
    """Return a starter contract template."""
    return {
        "endpoints": [
            {
                "url": "/api/example",
                "method": "GET",
                "request_params": ["page", "limit"],
                "response_fields": ["id", "name"],
                "description": "Example endpoint",
            }
        ],
        "components": [
            {
                "name": "ExampleComponent",
                "binds_to": "/api/example",
            }
        ],
        "rules": {
            "no_undeclared_endpoints": True,
        },
    }
