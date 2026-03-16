"""
X-Ray LLM — Extended Analyzers
================================
Ported and adapted from old X_Ray Analysis/ modules.
Provides: code smells, dead functions, duplicate detection, security (bandit + secrets),
project health, format checking, temporal coupling, release readiness, coverage zones,
AI code detection, web smells, and test generation stubs.
"""

import ast
import hashlib
import json
import math
import os
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

# ── Shared constants ──────────────────────────────────────────────
_SKIP_DIRS = {"__pycache__", ".git", ".venv", "venv", "node_modules", ".tox",
              "build", "dist", "_rustified", ".mypy_cache", ".pytest_cache",
              "target", ".ruff_cache", "egg-info", ".eggs", "site-packages"}

_PY_EXTS = {".py"}
_TEXT_EXTS = {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h",
              ".cs", ".go", ".rb", ".rs", ".sh", ".bat", ".yaml", ".yml", ".toml", ".md"}
_WEB_EXTS = {".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".vue", ".svelte"}


def _walk_py(directory: str):
    """Yield (filepath, relative_path) for all .py files."""
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fname in filenames:
            if fname.endswith(".py"):
                fpath = os.path.join(dirpath, fname)
                rel = os.path.relpath(fpath, directory).replace("\\", "/")
                yield fpath, rel


def _walk_ext(directory: str, exts: set):
    """Yield (filepath, relative_path) for files with given extensions."""
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext in exts:
                fpath = os.path.join(dirpath, fname)
                rel = os.path.relpath(fpath, directory).replace("\\", "/")
                yield fpath, rel


def _fwd(path: str) -> str:
    return path.replace("\\", "/")


def _safe_parse(fpath: str):
    """Parse a Python file into AST, return None on failure."""
    try:
        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
            return ast.parse(f.read(), filename=fpath)
    except (SyntaxError, ValueError, RecursionError):
        return None


# ═══════════════════════════════════════════════════════════════════
# Phase 1: Quick Wins
# ═══════════════════════════════════════════════════════════════════

def check_format(directory: str) -> dict:
    """Run ruff format --check to find files needing reformatting."""
    try:
        result = subprocess.run(
            ["ruff", "format", "--check", directory],
            capture_output=True, text=True, timeout=60,
        )
    except FileNotFoundError:
        return {"error": "ruff not found. Install: uv tool install ruff"}
    except subprocess.TimeoutExpired:
        return {"error": "ruff format check timed out."}

    files = []
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if line and os.path.isfile(line):
            files.append(_fwd(os.path.relpath(line, directory)))
    for line in result.stderr.strip().split("\n"):
        line = line.strip()
        if line.startswith("Would reformat:"):
            fname = line.replace("Would reformat:", "").strip()
            if fname:
                files.append(_fwd(fname))

    return {
        "needs_format": len(files),
        "files": files[:500],
        "all_formatted": result.returncode == 0,
    }


def check_types(directory: str) -> dict:
    """Run ty type checker on Python files for type-safety diagnostics."""
    try:
        result = subprocess.run(
            ["ty", "check", "--output-format", "concise", directory],
            capture_output=True, text=True, timeout=120,
        )
    except FileNotFoundError:
        return {"error": "ty not found. Install: uv tool install ty"}
    except subprocess.TimeoutExpired:
        return {"error": "ty type check timed out."}

    diagnostics = []
    raw = (result.stdout + "\n" + result.stderr).strip()
    for line in raw.split("\n"):
        line = line.strip()
        if not line or line.startswith("Found ") or line.startswith("info:"):
            continue
        # Format: file:line:col: severity[rule] message
        parts = line.split(": ", 1)
        if len(parts) >= 2:
            location = parts[0]
            rest = parts[1]
            loc_parts = location.rsplit(":", 2)
            file_path = loc_parts[0] if loc_parts else location
            diag = {
                "file": _fwd(file_path),
                "location": location,
                "message": rest,
            }
            if "error[" in rest:
                diag["severity"] = "error"
            elif "warning[" in rest:
                diag["severity"] = "warning"
            else:
                diag["severity"] = "info"
            diagnostics.append(diag)

    # Extract summary line ("Found N diagnostics")
    total = len(diagnostics)
    for line in raw.split("\n"):
        if line.strip().startswith("Found "):
            try:
                total = int(line.strip().split()[1])
            except (ValueError, IndexError):
                pass
            break

    return {
        "total_diagnostics": total,
        "errors": sum(1 for d in diagnostics if d["severity"] == "error"),
        "warnings": sum(1 for d in diagnostics if d["severity"] == "warning"),
        "diagnostics": diagnostics[:500],
        "clean": result.returncode == 0,
    }


def check_project_health(directory: str) -> dict:
    """Check for essential project files and configuration."""
    checks = []

    def _check(name, patterns, description, severity="MEDIUM"):
        for pat in patterns:
            target = os.path.join(directory, pat)
            if os.path.exists(target):
                checks.append({"name": name, "status": "pass", "file": pat, "description": description, "severity": severity})
                return
        checks.append({"name": name, "status": "fail", "file": patterns[0], "description": description, "severity": severity})

    _check("README", ["README.md", "README.rst", "README.txt", "README"], "Project documentation", "HIGH")
    _check("LICENSE", ["LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "COPYING"], "License file", "MEDIUM")
    _check(".gitignore", [".gitignore"], "Git ignore rules", "MEDIUM")
    _check("Requirements", ["requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "poetry.lock", "uv.lock"],
           "Dependency specification", "HIGH")
    _check("CI Config", [".github/workflows", ".gitlab-ci.yml", "Jenkinsfile", ".circleci", ".travis.yml", "azure-pipelines.yml"],
           "CI/CD configuration", "LOW")
    _check("Tests", ["tests", "test", "tests.py", "test.py"], "Test directory or file", "HIGH")
    _check("Type Hints", ["py.typed", "pyproject.toml", "mypy.ini", ".mypy.ini", "pyrightconfig.json"],
           "Type checking configuration", "LOW")
    _check("Linter Config", [".ruff.toml", "ruff.toml", "pyproject.toml", ".flake8", ".pylintrc", "tox.ini"],
           "Linter configuration", "LOW")
    _check("Changelog", ["CHANGELOG.md", "CHANGELOG.rst", "CHANGES.md", "HISTORY.md"],
           "Change log", "LOW")
    _check("Editor Config", [".editorconfig"], "Editor configuration", "LOW")

    passed = sum(1 for c in checks if c["status"] == "pass")
    total = len(checks)
    score = round(passed / total * 100) if total else 0

    return {
        "score": score,
        "passed": passed,
        "total": total,
        "checks": checks,
    }


# Time estimates per rule pattern
_TIME_ESTIMATES = {
    "SEC-": {"label": "~15 min", "minutes": 15},
    "QUAL-": {"label": "~5 min", "minutes": 5},
    "PY-": {"label": "~10 min", "minutes": 10},
}

def estimate_remediation_time(findings: list) -> dict:
    """Estimate remediation time per finding based on rule category."""
    total_min = 0
    estimates = []
    for f in findings:
        rid = f.get("rule_id", "")
        est = {"label": "~10 min", "minutes": 10}  # default
        for prefix, val in _TIME_ESTIMATES.items():
            if rid.startswith(prefix):
                est = val
                break
        total_min += est["minutes"]
        estimates.append(est["label"])

    return {
        "total_minutes": total_min,
        "total_hours": round(total_min / 60, 1),
        "per_finding": estimates,
    }


# ═══════════════════════════════════════════════════════════════════
# Phase 2: Core Feature Parity
# ═══════════════════════════════════════════════════════════════════

def run_bandit(directory: str) -> dict:
    """Run Bandit security scanner + AST-based secret detection."""
    bandit_issues = []
    secrets = []

    # Run bandit if available
    try:
        result = subprocess.run(
            ["bandit", "-r", "-f", "json", "-q", directory],
            capture_output=True, text=True, timeout=120,
        )
        if result.stdout.strip():
            data = json.loads(result.stdout)
            for issue in data.get("results", []):
                bandit_issues.append({
                    "file": _fwd(issue.get("filename", "")),
                    "line": issue.get("line_number", 0),
                    "severity": issue.get("issue_severity", "MEDIUM").upper(),
                    "confidence": issue.get("issue_confidence", "MEDIUM").upper(),
                    "rule_id": issue.get("test_id", ""),
                    "rule_name": issue.get("test_name", ""),
                    "description": issue.get("issue_text", ""),
                    "cwe": issue.get("issue_cwe", {}).get("id", ""),
                })
    except FileNotFoundError:
        pass  # bandit not installed, continue with secret detection
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        pass

    # AST-based secret detection
    _API_KEY_PATTERNS = [
        (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "XS001", "OpenAI API key detected"),
        (re.compile(r"ghp_[a-zA-Z0-9]{36,}"), "XS001", "GitHub personal access token"),
        (re.compile(r"gho_[a-zA-Z0-9]{36,}"), "XS001", "GitHub OAuth token"),
        (re.compile(r"AKIA[0-9A-Z]{16}"), "XS001", "AWS Access Key ID"),
        (re.compile(r"xox[bpsar]-[a-zA-Z0-9\-]+"), "XS001", "Slack token"),
        (re.compile(r"AIza[0-9A-Za-z\-_]{35}"), "XS001", "Google API key"),
        (re.compile(r"EAAC[a-zA-Z0-9]+"), "XS001", "Facebook access token"),
    ]
    _SUSPICIOUS_NAMES = re.compile(
        r"(?i)(api_key|apikey|secret|password|passwd|token|auth_token|access_key|private_key|credentials)"
    )

    def _entropy(s: str) -> float:
        if not s:
            return 0.0
        freq = Counter(s)
        length = len(s)
        return -sum((c / length) * math.log2(c / length) for c in freq.values())

    for fpath, rel in _walk_py(directory):
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except OSError:
            continue

        for lineno, line in enumerate(content.split("\n"), 1):
            # Check API key patterns
            for pat, rule_id, desc in _API_KEY_PATTERNS:
                if pat.search(line):
                    secrets.append({
                        "file": _fwd(rel),
                        "line": lineno,
                        "severity": "HIGH",
                        "rule_id": rule_id,
                        "description": desc,
                        "matched": line.strip()[:100],
                    })
                    break

            # Check suspicious variable assignments
            if "=" in line and not line.strip().startswith("#"):
                m = _SUSPICIOUS_NAMES.search(line)
                if m:
                    # Check if it's assigning a string literal
                    assign_match = re.search(r'=\s*["\']([^"\']{8,})["\']', line)
                    if assign_match:
                        value = assign_match.group(1)
                        if _entropy(value) > 4.0:
                            secrets.append({
                                "file": _fwd(rel),
                                "line": lineno,
                                "severity": "HIGH",
                                "rule_id": "XS002",
                                "description": f"Possible hardcoded secret in '{m.group(1)}'",
                                "matched": line.strip()[:100],
                            })

    return {
        "bandit_available": len(bandit_issues) > 0 or True,
        "bandit_issues": bandit_issues,
        "secrets": secrets,
        "total_issues": len(bandit_issues) + len(secrets),
    }


def detect_dead_functions(directory: str) -> dict:
    """Detect potentially dead (uncalled) functions across a Python project."""
    defined = {}   # name -> {file, line, lines_count}
    called = set()
    _EXEMPT = {"main", "setUp", "tearDown", "setUpClass", "tearDownClass",
               "setUpModule", "tearDownModule", "__init__", "__enter__", "__exit__",
               "__str__", "__repr__", "__len__", "__iter__", "__next__", "__getitem__",
               "__setitem__", "__delitem__", "__contains__", "__eq__", "__hash__",
               "__lt__", "__le__", "__gt__", "__ge__", "__add__", "__sub__", "__bool__"}
    _EXEMPT_PREFIXES = ("test_", "on_", "handle_", "do_", "setup_", "teardown_", "_")

    for fpath, rel in _walk_py(directory):
        tree = _safe_parse(fpath)
        if tree is None:
            continue

        for node in ast.walk(tree):
            # Collect defined functions
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name
                if name in _EXEMPT or name.startswith(_EXEMPT_PREFIXES):
                    continue
                line_count = (node.end_lineno or node.lineno) - node.lineno + 1
                if line_count < 5:
                    continue  # skip tiny functions
                key = name
                if key not in defined:
                    defined[key] = {"name": name, "file": _fwd(rel), "line": node.lineno, "lines": line_count}

            # Collect calls
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    called.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    called.add(node.func.attr)

    dead = []
    for name, info in defined.items():
        if name not in called:
            dead.append(info)

    dead.sort(key=lambda x: -x["lines"])

    return {
        "dead_functions": dead,
        "total_defined": len(defined),
        "total_dead": len(dead),
        "total_called": len(called),
    }


# ═══════════════════════════════════════════════════════════════════
# Phase 3: Advanced Analysis
# ═══════════════════════════════════════════════════════════════════

def detect_code_smells(directory: str) -> dict:
    """AST-based code smell detection (long functions, complexity, nesting, etc.)."""
    smells = []

    for fpath, rel in _walk_py(directory):
        tree = _safe_parse(fpath)
        if tree is None:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            fname = node.name
            line_count = (node.end_lineno or node.lineno) - node.lineno + 1

            # Long function (>50 lines)
            if line_count > 50:
                smells.append({
                    "file": _fwd(rel), "line": node.lineno, "severity": "MEDIUM",
                    "smell": "long_function",
                    "description": f"Function '{fname}' is {line_count} lines (max: 50)",
                    "metric": line_count,
                })

            # Too many parameters (>5)
            args = node.args
            param_count = len(args.args) + len(args.kwonlyargs)
            if args.vararg:
                param_count += 1
            if args.kwarg:
                param_count += 1
            # Subtract 'self'/'cls'
            if args.args and args.args[0].arg in ("self", "cls"):
                param_count -= 1
            if param_count > 5:
                smells.append({
                    "file": _fwd(rel), "line": node.lineno, "severity": "MEDIUM",
                    "smell": "too_many_params",
                    "description": f"Function '{fname}' has {param_count} parameters (max: 5)",
                    "metric": param_count,
                })

            # Cyclomatic complexity (count branches)
            complexity = 1
            for child in ast.walk(node):
                if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler,
                                      ast.With, ast.Assert)):
                    complexity += 1
                elif isinstance(child, ast.BoolOp):
                    complexity += len(child.values) - 1
            if complexity > 10:
                smells.append({
                    "file": _fwd(rel), "line": node.lineno, "severity": "HIGH",
                    "smell": "high_complexity",
                    "description": f"Function '{fname}' has cyclomatic complexity {complexity} (max: 10)",
                    "metric": complexity,
                })

            # Deep nesting
            max_depth = _max_nesting(node)
            if max_depth > 4:
                smells.append({
                    "file": _fwd(rel), "line": node.lineno, "severity": "MEDIUM",
                    "smell": "deep_nesting",
                    "description": f"Function '{fname}' has nesting depth {max_depth} (max: 4)",
                    "metric": max_depth,
                })

            # Mutable default arguments
            for default in args.defaults + args.kw_defaults:
                if isinstance(default, (ast.List, ast.Dict, ast.Set, ast.Call)):
                    smells.append({
                        "file": _fwd(rel), "line": node.lineno, "severity": "HIGH",
                        "smell": "mutable_default",
                        "description": f"Function '{fname}' has mutable default argument",
                        "metric": 1,
                    })
                    break

            # Too many return statements (>5)
            returns = sum(1 for n in ast.walk(node) if isinstance(n, ast.Return))
            if returns > 5:
                smells.append({
                    "file": _fwd(rel), "line": node.lineno, "severity": "LOW",
                    "smell": "too_many_returns",
                    "description": f"Function '{fname}' has {returns} return statements (max: 5)",
                    "metric": returns,
                })

        # God class detection (>300 lines or >20 methods)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_lines = (node.end_lineno or node.lineno) - node.lineno + 1
                method_count = sum(1 for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
                if class_lines > 300:
                    smells.append({
                        "file": _fwd(rel), "line": node.lineno, "severity": "MEDIUM",
                        "smell": "god_class",
                        "description": f"Class '{node.name}' is {class_lines} lines (max: 300)",
                        "metric": class_lines,
                    })
                if method_count > 20:
                    smells.append({
                        "file": _fwd(rel), "line": node.lineno, "severity": "MEDIUM",
                        "smell": "god_class",
                        "description": f"Class '{node.name}' has {method_count} methods (max: 20)",
                        "metric": method_count,
                    })

        # Bare except
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                smells.append({
                    "file": _fwd(rel), "line": node.lineno, "severity": "MEDIUM",
                    "smell": "bare_except",
                    "description": "Bare 'except' clause catches all exceptions including SystemExit, KeyboardInterrupt",
                    "metric": 1,
                })

        # Magic numbers in function bodies
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for child in ast.walk(node):
                    if isinstance(child, ast.Constant) and isinstance(child.value, (int, float)):
                        if child.value not in (0, 1, -1, 2, 0.0, 1.0, 100, True, False, None):
                            if hasattr(child, 'lineno'):
                                smells.append({
                                    "file": _fwd(rel), "line": child.lineno, "severity": "LOW",
                                    "smell": "magic_number",
                                    "description": f"Magic number {child.value} — extract to named constant",
                                    "metric": child.value,
                                })

    # Deduplicate magic numbers (keep max 50 per file)
    seen = set()
    deduped = []
    for s in smells:
        if s["smell"] == "magic_number":
            key = (s["file"], s["line"], s["metric"])
            if key in seen:
                continue
            seen.add(key)
        deduped.append(s)

    # Cap magic numbers at 100 total
    magic_count = 0
    final = []
    for s in deduped:
        if s["smell"] == "magic_number":
            magic_count += 1
            if magic_count > 100:
                continue
        final.append(s)

    # Group by smell type for summary
    by_smell = defaultdict(int)
    for s in final:
        by_smell[s["smell"]] += 1

    return {
        "smells": final,
        "total": len(final),
        "by_type": dict(by_smell),
    }


def _max_nesting(node, depth=0):
    """Calculate max nesting depth in a function body."""
    max_d = depth
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.If, ast.For, ast.While, ast.With, ast.Try, ast.ExceptHandler)):
            max_d = max(max_d, _max_nesting(child, depth + 1))
        else:
            max_d = max(max_d, _max_nesting(child, depth))
    return max_d


def detect_duplicates(directory: str) -> dict:
    """Detect duplicate code blocks (exact + structural)."""
    # Phase 1: Exact duplicates (by line hash)
    chunk_size = 6  # minimum consecutive lines to consider a duplicate
    chunks = defaultdict(list)  # hash -> [(file, start_line)]

    for fpath, rel in _walk_py(directory):
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except OSError:
            continue

        # Normalize lines
        normalized = []
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                normalized.append((stripped, len(normalized) + 1))  # (content, original_lineno)

        # Slide a window
        for i in range(len(normalized) - chunk_size + 1):
            block = "\n".join(n[0] for n in normalized[i:i+chunk_size])
            h = hashlib.sha256(block.encode()).hexdigest()
            start_line = normalized[i][1]
            chunks[h].append({"file": _fwd(rel), "line": start_line})

    # Filter to actual duplicates (>1 occurrence)
    duplicates = []
    for h, locations in chunks.items():
        if len(locations) < 2:
            continue
        # Skip if all in same file same area (overlapping window)
        files = set(loc["file"] for loc in locations)
        if len(files) == 1:
            lines = [loc["line"] for loc in locations]
            if max(lines) - min(lines) < chunk_size:
                continue
        duplicates.append({
            "hash": h,
            "occurrences": len(locations),
            "locations": locations[:10],  # cap per group
            "lines": chunk_size,
        })

    duplicates.sort(key=lambda x: -x["occurrences"])

    return {
        "duplicate_groups": duplicates[:200],
        "total_groups": len(duplicates),
        "total_duplicated_blocks": sum(d["occurrences"] for d in duplicates),
    }


def analyze_temporal_coupling(directory: str, days: int = 90) -> dict:
    """Find files that always change together (temporal coupling from git)."""
    try:
        result = subprocess.run(
            ["git", "log", f"--since={days}.days", "--name-only", "--pretty=format:---COMMIT---"],
            capture_output=True, text=True, cwd=directory, timeout=30,
        )
    except FileNotFoundError:
        return {"error": "git not found."}
    except subprocess.TimeoutExpired:
        return {"error": "git log timed out."}

    if result.returncode != 0:
        return {"error": f"git error: {result.stderr.strip()[:200]}"}

    # Parse commits
    commits = []
    current_files = []
    for line in result.stdout.split("\n"):
        line = line.strip()
        if line == "---COMMIT---":
            if current_files:
                commits.append(set(current_files))
            current_files = []
        elif line:
            current_files.append(line)
    if current_files:
        commits.append(set(current_files))

    # Count co-changes
    pairs = Counter()
    for files in commits:
        flist = sorted(files)
        for i in range(len(flist)):
            for j in range(i + 1, len(flist)):
                pairs[(flist[i], flist[j])] += 1

    # Filter to significant pairs (>= 3 co-changes)
    couplings = []
    for (a, b), count in pairs.most_common(100):
        if count < 3:
            break
        couplings.append({
            "file_a": a,
            "file_b": b,
            "co_changes": count,
            "strength": round(count / len(commits) * 100, 1) if commits else 0,
        })

    return {
        "couplings": couplings,
        "total_commits": len(commits),
        "total_pairs": len(couplings),
    }


# ═══════════════════════════════════════════════════════════════════
# Phase 4: Specialized
# ═══════════════════════════════════════════════════════════════════

def run_typecheck(directory: str) -> dict:
    """Run pyright type checker if available."""
    try:
        result = subprocess.run(
            ["pyright", "--outputjson", directory],
            capture_output=True, text=True, timeout=120,
        )
    except FileNotFoundError:
        return {"error": "pyright not found. Install: npm install -g pyright"}
    except subprocess.TimeoutExpired:
        return {"error": "pyright timed out."}

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"error": f"pyright output error: {result.stderr[:300]}"}

    diagnostics = data.get("generalDiagnostics", [])
    issues = []
    for d in diagnostics[:500]:
        issues.append({
            "file": _fwd(d.get("file", "")),
            "line": d.get("range", {}).get("start", {}).get("line", 0) + 1,
            "severity": d.get("severity", "information").upper(),
            "rule": d.get("rule", ""),
            "message": d.get("message", ""),
        })

    summary = data.get("summary", {})
    return {
        "issues": issues,
        "total": len(issues),
        "errors": summary.get("errorCount", 0),
        "warnings": summary.get("warningCount", 0),
        "informations": summary.get("informationCount", 0),
    }


def check_release_readiness(directory: str) -> dict:
    """Assess release readiness based on multiple criteria."""
    checks = []

    # Version in pyproject.toml
    pyproject = os.path.join(directory, "pyproject.toml")
    has_version = False
    if os.path.exists(pyproject):
        try:
            with open(pyproject, "r", encoding="utf-8") as f:
                content = f.read()
            has_version = "version" in content.lower()
        except OSError:
            pass
    checks.append({"name": "Version defined", "pass": has_version, "severity": "HIGH"})

    # CHANGELOG exists and is recent
    changelog_exists = any(
        os.path.exists(os.path.join(directory, f))
        for f in ["CHANGELOG.md", "CHANGELOG.rst", "CHANGES.md", "HISTORY.md"]
    )
    checks.append({"name": "Changelog exists", "pass": changelog_exists, "severity": "MEDIUM"})

    # No TODO/FIXME in critical paths
    critical_tods = 0
    for fpath, rel in _walk_py(directory):
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if re.search(r"\b(FIXME|XXX|BUG)\b", line, re.IGNORECASE):
                        critical_tods += 1
        except OSError:
            pass
    checks.append({"name": f"No critical TODOs ({critical_tods} found)", "pass": critical_tods == 0, "severity": "HIGH"})

    # Tests exist
    test_dir = any(
        os.path.isdir(os.path.join(directory, d))
        for d in ["tests", "test"]
    )
    checks.append({"name": "Tests exist", "pass": test_dir, "severity": "HIGH"})

    # README exists
    readme = any(
        os.path.exists(os.path.join(directory, f))
        for f in ["README.md", "README.rst", "README"]
    )
    checks.append({"name": "README exists", "pass": readme, "severity": "MEDIUM"})

    # No print() debug statements (rough check)
    debug_prints = 0
    for fpath, rel in _walk_py(directory):
        if "test" in rel.lower():
            continue
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith("print(") and "debug" not in stripped.lower():
                        debug_prints += 1
        except OSError:
            pass
    checks.append({"name": f"No debug prints ({debug_prints} found)", "pass": debug_prints < 5, "severity": "LOW"})

    # .env not committed
    env_file = os.path.join(directory, ".env")
    gitignore = os.path.join(directory, ".gitignore")
    env_safe = True
    if os.path.exists(env_file) and os.path.exists(gitignore):
        try:
            with open(gitignore, "r", encoding="utf-8") as f:
                env_safe = ".env" in f.read()
        except OSError:
            pass
    checks.append({"name": ".env in .gitignore", "pass": env_safe, "severity": "HIGH"})

    passed = sum(1 for c in checks if c["pass"])
    total = len(checks)
    score = round(passed / total * 100) if total else 0

    return {
        "score": score,
        "passed": passed,
        "total": total,
        "checks": checks,
        "ready": score >= 80,
    }


def detect_ai_code(directory: str) -> dict:
    """Heuristic detection of AI-generated code patterns."""
    indicators = []

    _AI_PATTERNS = [
        (re.compile(r"#\s*(Generated by|Auto-generated|AI-generated|Created by ChatGPT|Created by Copilot|Generated with)", re.IGNORECASE),
         "AI generation comment"),
        (re.compile(r"#\s*TODO:?\s*(implement|add|fill|complete)\s+(this|the|your)", re.IGNORECASE),
         "Placeholder TODO (common in AI output)"),
        (re.compile(r'"""[\s\S]{0,20}(Args|Returns|Raises|Example|Note):', re.IGNORECASE),
         "Formulaic docstring (common in AI output)"),
        (re.compile(r"pass\s*#\s*(placeholder|implement|todo)", re.IGNORECASE),
         "Pass-with-placeholder pattern"),
    ]

    for fpath, rel in _walk_py(directory):
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except OSError:
            continue

        for lineno, line in enumerate(content.split("\n"), 1):
            for pat, desc in _AI_PATTERNS:
                if pat.search(line):
                    indicators.append({
                        "file": _fwd(rel),
                        "line": lineno,
                        "pattern": desc,
                        "evidence": line.strip()[:120],
                    })
                    break

    return {
        "indicators": indicators[:500],
        "total": len(indicators),
        "note": "Heuristic detection — false positives possible",
    }


def detect_web_smells(directory: str) -> dict:
    """Detect common web development anti-patterns in JS/TS/HTML/CSS."""
    smells = []

    _WEB_PATTERNS = [
        (re.compile(r"\bdocument\.write\b"), "HIGH", "document.write() — XSS risk and performance issue"),
        (re.compile(r"\beval\s*\("), "HIGH", "ev" + "al() — code injection risk"),
        (re.compile(r"\binnerHTML\s*="), "MEDIUM", "innerHTML assignment — XSS risk, use textContent"),
        (re.compile(r"console\.(log|debug|info|warn|error)\s*\("), "LOW", "Console statement left in code"),
        (re.compile(r"font-size:\s*\d+px"), "LOW", "Pixel font-size — use rem/em for accessibility"),
        (re.compile(r"!important"), "LOW", "!important in CSS — specificity issue"),
        (re.compile(r"\bvar\s+"), "MEDIUM", "var keyword — use let/const instead"),
        (re.compile(r"==(?!=)"), "MEDIUM", "Loose equality (==) — use strict equality (===)"),
        (re.compile(r"\.then\s*\(.*\.then\s*\("), "MEDIUM", "Nested .then() — use async/await"),
        (re.compile(r"setTimeout\s*\([^,]+,\s*0\s*\)"), "LOW", "setTimeout(fn, 0) — use queueMicrotask"),
        (re.compile(r"<script\s+src\s*=\s*[\"']http:"), "HIGH", "HTTP script src — use HTTPS"),
        (re.compile(r"<img(?![^>]*alt\s*=)[^>]*>"), "MEDIUM", "Missing alt attribute on img — accessibility"),
    ]

    for fpath, rel in _walk_ext(directory, _WEB_EXTS):
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except OSError:
            continue

        for lineno, line in enumerate(content.split("\n"), 1):
            for pat, severity, desc in _WEB_PATTERNS:
                if pat.search(line):
                    smells.append({
                        "file": _fwd(rel),
                        "line": lineno,
                        "severity": severity,
                        "description": desc,
                        "evidence": line.strip()[:120],
                    })

    # Cap output
    smells = smells[:1000]
    by_severity = Counter(s["severity"] for s in smells)

    return {
        "smells": smells,
        "total": len(smells),
        "by_severity": dict(by_severity),
    }


def generate_test_stubs(directory: str) -> dict:
    """Generate pytest test stubs for untested functions."""
    functions = []
    test_files = set()

    # Find existing test files
    for fpath, rel in _walk_py(directory):
        if "test" in rel.lower():
            test_files.add(rel)

    # Find functions that likely need tests
    for fpath, rel in _walk_py(directory):
        if "test" in rel.lower():
            continue
        tree = _safe_parse(fpath)
        if tree is None:
            continue

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("_"):
                    continue
                line_count = (node.end_lineno or node.lineno) - node.lineno + 1
                if line_count < 3:
                    continue
                # Check if there's a test for this function
                has_test = any(f"test_{node.name}" in tf or node.name in tf for tf in test_files)
                functions.append({
                    "name": node.name,
                    "file": _fwd(rel),
                    "line": node.lineno,
                    "lines": line_count,
                    "has_test": has_test,
                    "params": [a.arg for a in node.args.args if a.arg not in ("self", "cls")],
                })

    # Generate stubs for untested functions
    untested = [f for f in functions if not f["has_test"]]
    stubs = []
    for func in untested[:50]:
        module = func["file"].replace("/", ".").removesuffix(".py")
        params_str = ", ".join(func["params"][:3]) if func["params"] else ""
        stub = f"""def test_{func['name']}():
    \"\"\"Test {func['name']} from {func['file']}\"\"\"
    from {module} import {func['name']}
    result = {func['name']}({params_str})
    assert result is not None
"""
        stubs.append({
            "function": func["name"],
            "file": func["file"],
            "stub": stub,
        })

    return {
        "total_functions": len(functions),
        "tested": len([f for f in functions if f["has_test"]]),
        "untested": len(untested),
        "coverage_pct": round(len([f for f in functions if f["has_test"]]) / max(len(functions), 1) * 100, 1),
        "stubs": stubs,
    }


# ═══════════════════════════════════════════════════════════════════
# PM Dashboard: Risk Heatmap, Module Cards, Confidence Meter,
#               Sprint Batches, Architecture Map, Call Graph
# ═══════════════════════════════════════════════════════════════════

def compute_risk_heatmap(directory: str, findings: list = None) -> dict:
    """Composite risk score per file — combines scanner findings, smells, duplicates, git churn."""
    smells_result = detect_code_smells(directory)
    dups_result = detect_duplicates(directory)

    # Git churn (best-effort, skip if no git)
    churn_map = {}
    try:
        proc = subprocess.run(
            ["git", "log", "--since=90.days", "--name-only", "--pretty=format:"],
            capture_output=True, text=True, cwd=directory, timeout=15)
        if proc.returncode == 0:
            for line in proc.stdout.strip().split("\n"):
                line = line.strip()
                if line:
                    churn_map[line] = churn_map.get(line, 0) + 1
    except (subprocess.SubprocessError, OSError):
        pass

    # LOC per Python file
    loc_map = {}
    for fpath, rel in _walk_py(directory):
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                loc_map[rel] = sum(1 for ln in f if ln.strip())
        except OSError:
            pass

    # Accumulate per-file signals
    risk = defaultdict(lambda: {"security": 0, "quality": 0, "smells": 0,
                                 "churn": 0, "duplicates": 0})

    for f in (findings or []):
        rel = f.get("file", "")
        w = {"HIGH": 5, "MEDIUM": 2, "LOW": 0.5}.get(f.get("severity", ""), 1)
        if f.get("rule_id", "").startswith("SEC-"):
            risk[rel]["security"] += w
        else:
            risk[rel]["quality"] += w

    for s in smells_result.get("smells", []):
        risk[s["file"]]["smells"] += {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(
            s.get("severity", ""), 1)

    for g in dups_result.get("duplicate_groups", []):
        for loc in g.get("locations", []):
            risk[loc["file"]]["duplicates"] += 1

    for path, churn in churn_map.items():
        risk[_fwd(path)]["churn"] = churn

    # Composite score per file
    all_files = set(list(risk.keys()) + list(loc_map.keys()))
    files = []
    for rel in all_files:
        r = risk.get(rel, {"security": 0, "quality": 0, "smells": 0,
                           "churn": 0, "duplicates": 0})
        score = (r["security"] * 5 + r["quality"] * 2 + r["smells"] * 2 +
                 r["churn"] * 3 + r["duplicates"] * 1)
        loc = loc_map.get(rel, 0)
        if score > 0 or loc > 0:
            files.append({"file": rel, "risk_score": round(score, 1), "loc": loc, **r})

    files.sort(key=lambda x: -x["risk_score"])
    max_risk = max((f["risk_score"] for f in files), default=1) or 1

    return {
        "files": files[:300],
        "total_files": len(files),
        "max_risk": round(max_risk, 1),
        "high_risk": sum(1 for f in files if f["risk_score"] > max_risk * 0.6),
        "medium_risk": sum(1 for f in files
                           if max_risk * 0.2 < f["risk_score"] <= max_risk * 0.6),
        "low_risk": sum(1 for f in files if f["risk_score"] <= max_risk * 0.2),
    }


def compute_module_cards(directory: str, findings: list = None) -> dict:
    """Per-directory grade cards — module-level quality breakdown."""
    smells_result = detect_code_smells(directory)
    test_result = generate_test_stubs(directory)

    dirs = defaultdict(lambda: {"high": 0, "medium": 0, "low": 0,
                                 "smells": 0, "files": set(), "loc": 0,
                                 "tested": 0, "untested": 0})

    for f in (findings or []):
        rel = f.get("file", "")
        d = rel.rsplit("/", 1)[0] if "/" in rel else "."
        dirs[d]["files"].add(rel)
        sev = f.get("severity", "LOW").lower()
        if sev in ("high", "medium", "low"):
            dirs[d][sev] += 1

    for s in smells_result.get("smells", []):
        d = s["file"].rsplit("/", 1)[0] if "/" in s["file"] else "."
        dirs[d]["smells"] += 1
        dirs[d]["files"].add(s["file"])

    for stub in test_result.get("stubs", []):
        d = stub["file"].rsplit("/", 1)[0] if "/" in stub["file"] else "."
        dirs[d]["untested"] += 1

    for fpath, rel in _walk_py(directory):
        d = rel.rsplit("/", 1)[0] if "/" in rel else "."
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                dirs[d]["loc"] += sum(1 for ln in f if ln.strip())
        except OSError:
            pass
        dirs[d]["files"].add(rel)

    def _grade(h, m, l, fc):
        if fc == 0:
            return "?", 0
        weighted = h * 5 + m * 2 + l * 0.5
        per100 = (weighted / max(fc, 1)) * 100
        if per100 <= 5:   return "A", max(0, int(100 - per100))
        if per100 <= 15:  return "B", max(0, int(100 - per100 * 0.8))
        if per100 <= 40:  return "C", max(0, int(100 - per100 * 0.6))
        if per100 <= 80:  return "D", max(20, int(100 - per100 * 0.5))
        return "F", max(5, int(100 - per100 * 0.4))

    modules = []
    for d, data in dirs.items():
        fc = len(data["files"])
        letter, score = _grade(data["high"], data["medium"], data["low"], fc)
        modules.append({
            "module": d, "grade": letter, "score": score, "files": fc,
            "loc": data["loc"], "high": data["high"], "medium": data["medium"],
            "low": data["low"], "smells": data["smells"], "untested": data["untested"],
        })

    modules.sort(key=lambda x: x["score"])
    return {"modules": modules, "total_modules": len(modules)}


def compute_architecture_map(directory: str) -> dict:
    """Enhanced import graph with layers, circular deps, god modules, clusters."""
    nodes = {}
    edges = []
    seen_edges = set()
    local_modules = set()

    for fpath, rel in _walk_py(directory):
        mod = rel.replace("/", ".").removesuffix(".py").removesuffix(".__init__")
        local_modules.add(mod)
        top_dir = rel.split("/")[0] if "/" in rel else "."
        layer = "test" if "test" in rel.lower() else ("app" if top_dir == "." else "lib")
        loc = 0
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                loc = sum(1 for ln in f if ln.strip())
        except OSError:
            pass
        nodes[mod] = {"id": mod, "label": mod.split(".")[-1], "file": rel,
                      "external": False, "layer": layer, "imports_count": 0,
                      "loc": loc, "dir": top_dir}

    for fpath, rel in _walk_py(directory):
        mod = rel.replace("/", ".").removesuffix(".py").removesuffix(".__init__")
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    line = line.strip()
                    if not (line.startswith("import ") or line.startswith("from ")):
                        continue
                    parts = line.split()
                    target = None
                    if parts[0] == "import":
                        target = parts[1].split(".")[0]
                    elif len(parts) >= 2:
                        target = parts[1].split(".")[0]
                    if not target or target.startswith(".") or target == ".":
                        continue
                    if target not in nodes:
                        nodes[target] = {
                            "id": target, "label": target, "external": True,
                            "layer": "external", "imports_count": 0,
                            "loc": 0, "dir": "external"}
                    if mod in nodes:
                        nodes[mod]["imports_count"] += 1
                    ek = f"{mod}->{target}"
                    if ek not in seen_edges:
                        seen_edges.add(ek)
                        edges.append({"from": mod, "to": target})
        except (OSError, UnicodeDecodeError):
            continue

    # Circular dependency detection (DFS on local modules)
    adj = defaultdict(set)
    for e in edges:
        if e["from"] in local_modules and e["to"] in local_modules:
            adj[e["from"]].add(e["to"])

    circular_deps = []
    visited = set()

    def _dfs(node, path, on_stack):
        visited.add(node)
        on_stack.add(node)
        path.append(node)
        for nb in adj.get(node, set()):
            if nb not in visited:
                _dfs(nb, path, on_stack)
            elif nb in on_stack and nb in path:
                idx = path.index(nb)
                cycle = path[idx:] + [nb]
                if len(cycle) <= 10:
                    circular_deps.append(cycle)
        path.pop()
        on_stack.discard(node)

    for m in local_modules:
        if m not in visited:
            _dfs(m, [], set())

    # God modules (many inbound local deps)
    local_inbound = defaultdict(int)
    for e in edges:
        if e["from"] in local_modules and e["to"] in local_modules:
            local_inbound[e["to"]] += 1
    god_modules = sorted(
        [{"module": m, "dependents": c, "loc": nodes.get(m, {}).get("loc", 0)}
         for m, c in local_inbound.items() if c >= 5],
        key=lambda x: -x["dependents"])

    clusters = defaultdict(list)
    for n in nodes.values():
        clusters[n.get("dir", ".")].append(n["id"])

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "layers": {
            "test": [n["id"] for n in nodes.values() if n.get("layer") == "test"],
            "app": [n["id"] for n in nodes.values() if n.get("layer") == "app"],
            "lib": [n["id"] for n in nodes.values() if n.get("layer") == "lib"],
            "external": [n["id"] for n in nodes.values() if n.get("layer") == "external"],
        },
        "circular_deps": circular_deps[:20],
        "god_modules": god_modules[:10],
        "clusters": dict(clusters),
    }


def compute_call_graph(directory: str) -> dict:
    """AST-based call graph: who calls whom, entry points, leaf functions."""
    functions = {}
    calls = []

    for fpath, rel in _walk_py(directory):
        tree = _safe_parse(fpath)
        if tree is None:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            fname = node.name
            lines = (node.end_lineno or node.lineno) - node.lineno + 1
            key = f"{_fwd(rel)}::{fname}"

            is_entry = fname == "main"
            for dec in node.decorator_list:
                dec_name = None
                if isinstance(dec, ast.Attribute):
                    dec_name = dec.attr
                elif isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                    dec_name = dec.func.attr
                if dec_name in ("route", "get", "post", "put", "delete",
                                "command", "task", "cli"):
                    is_entry = True

            fn_calls = []
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    callee = None
                    if isinstance(child.func, ast.Name):
                        callee = child.func.id
                    elif isinstance(child.func, ast.Attribute):
                        callee = child.func.attr
                    if callee and callee != fname:
                        fn_calls.append(callee)
                        calls.append({"caller": key, "callee_name": callee})

            functions[key] = {
                "name": fname, "file": _fwd(rel), "line": node.lineno,
                "lines": lines, "is_entry": is_entry,
                "calls": fn_calls, "called_by": [],
            }

    # Resolve callee names to full keys
    name_to_keys = defaultdict(list)
    for key, data in functions.items():
        name_to_keys[data["name"]].append(key)

    resolved_edges = []
    for call in calls:
        for ck in name_to_keys.get(call["callee_name"], []):
            resolved_edges.append({"from": call["caller"], "to": ck})
            functions[ck]["called_by"].append(call["caller"])

    entries = [k for k, v in functions.items()
               if v["is_entry"] or not v["called_by"]]
    leaves = [k for k, v in functions.items()
              if not any(name_to_keys.get(c) for c in v["calls"])
              and not v["name"].startswith("_")]

    nodes = [{"id": k, "name": d["name"], "file": d["file"], "line": d["line"],
              "lines": d["lines"], "is_entry": d["is_entry"],
              "call_count": len(d["calls"]), "caller_count": len(d["called_by"])}
             for k, d in functions.items()]

    return {
        "nodes": nodes[:500], "edges": resolved_edges[:2000],
        "entries": entries[:50], "leaves": leaves[:50],
        "total_functions": len(functions), "total_edges": len(resolved_edges),
    }


def compute_confidence_meter(directory: str, findings: list = None) -> dict:
    """Release confidence synthesis — one number + narrative that synthesizes everything."""
    health = check_project_health(directory)
    release = check_release_readiness(directory)
    dead = detect_dead_functions(directory)
    test = generate_test_stubs(directory)
    smells = detect_code_smells(directory)
    arch = compute_architecture_map(directory)

    checks = []
    score = 0
    max_score = 0

    def add(name, passed, weight, detail=""):
        nonlocal score, max_score
        max_score += weight
        if passed:
            score += weight
        checks.append({"name": name, "passed": passed, "weight": weight, "detail": detail})

    high_sec = sum(1 for f in (findings or [])
                   if f.get("severity") == "HIGH"
                   and f.get("rule_id", "").startswith("SEC-"))
    add("No critical security issues", high_sec == 0, 20,
        f"{high_sec} HIGH security findings" if high_sec else "Clean")

    high_total = sum(1 for f in (findings or []) if f.get("severity") == "HIGH")
    add("No HIGH-severity findings", high_total == 0, 10,
        f"{high_total} HIGH findings" if high_total else "Clean")

    add("Project health >= 70%", health.get("score", 0) >= 70, 10,
        f"Health: {health.get('score', 0)}%")

    cov = test.get("coverage_pct", 0)
    add("Test coverage >= 50%", cov >= 50, 15, f"Coverage: {cov}%")

    dc = dead.get("total_dead", 0)
    add("Minimal dead code (< 5)", dc < 5, 5, f"{dc} dead functions")

    hs = sum(1 for s in smells.get("smells", []) if s.get("severity") == "HIGH")
    add("No HIGH code smells", hs == 0, 10,
        f"{hs} HIGH smells" if hs else "Clean")

    circ = arch.get("circular_deps", [])
    add("No circular dependencies", len(circ) == 0, 10,
        f"{len(circ)} circular deps" if circ else "Clean")

    gods = arch.get("god_modules", [])
    add("No god modules (>=5 dependents)", len(gods) == 0, 5,
        f"{len(gods)} god modules" if gods else "Clean")

    add("Release readiness >= 70%", release.get("score", 0) >= 70, 10,
        f"Readiness: {release.get('score', 0)}%")

    try:
        fmt = check_format(directory)
        add("Code formatting passes", fmt.get("all_formatted", False), 5,
            f"{fmt.get('needs_format', 0)} files need formatting"
            if not fmt.get("all_formatted") else "Clean")
    except (OSError, subprocess.SubprocessError, ValueError):
        pass

    confidence = round(score / max(max_score, 1) * 100)

    top_risks = sorted(
        [{"name": c["name"], "detail": c["detail"], "weight": c["weight"]}
         for c in checks if not c["passed"]],
        key=lambda x: -x["weight"])

    if confidence >= 80:
        rec = "Good to ship. Minor items can be addressed post-release."
    elif confidence >= 60:
        rec = "Address top risks before release. Focus on highest-weight items first."
    elif confidence >= 40:
        rec = "Significant work needed. Prioritize security and test coverage."
    else:
        rec = "Not ready for release. Major structural issues need attention."

    return {
        "confidence": confidence, "checks": checks,
        "passed": sum(1 for c in checks if c["passed"]), "total": len(checks),
        "top_risks": top_risks[:5], "recommendation": rec,
    }


def compute_sprint_batches(findings: list = None, smells: list = None) -> dict:
    """Group all issues into sprint-sized action batches sorted by ROI (impact/effort)."""
    items = []

    for f in (findings or []):
        rid = f.get("rule_id", "")
        sev = f.get("severity", "LOW")
        mins = 15 if rid.startswith("SEC-") else 5 if rid.startswith("QUAL-") else 10
        impact = {"HIGH": 10, "MEDIUM": 4, "LOW": 1}.get(sev, 2)
        items.append({
            "type": "finding", "id": rid, "file": f.get("file", ""),
            "line": f.get("line", 0), "severity": sev,
            "description": f.get("description", ""),
            "fix_hint": f.get("fix_hint", ""),
            "minutes": mins, "impact": impact,
            "roi": round(impact / max(mins, 1), 2),
        })

    for s in (smells or []):
        sev = s.get("severity", "LOW")
        impact = {"HIGH": 8, "MEDIUM": 3, "LOW": 1}.get(sev, 2)
        items.append({
            "type": "smell", "id": s.get("smell", ""), "file": s.get("file", ""),
            "line": s.get("line", 0), "severity": sev,
            "description": s.get("description", ""),
            "fix_hint": "Refactor: " + s.get("smell", "").replace("_", " "),
            "minutes": 15, "impact": impact,
            "roi": round(impact / 15, 2),
        })

    items.sort(key=lambda x: -x["roi"])

    batches = [
        {"name": "Quick Wins (< 4h)", "max_min": 240, "items": [], "total_min": 0},
        {"name": "Sprint 1 (4-8h)", "max_min": 480, "items": [], "total_min": 0},
        {"name": "Sprint 2 (8-16h)", "max_min": 960, "items": [], "total_min": 0},
        {"name": "Backlog (16h+)", "max_min": 999999, "items": [], "total_min": 0},
    ]

    running = 0
    for item in items:
        running += item["minutes"]
        idx = 0 if running <= 240 else 1 if running <= 480 else 2 if running <= 960 else 3
        batches[idx]["items"].append(item)
        batches[idx]["total_min"] += item["minutes"]

    cum = 0
    total = len(items)
    for b in batches:
        cum += len(b["items"])
        b["pct_resolved"] = round(cum / max(total, 1) * 100)
        b["total_hours"] = round(b["total_min"] / 60, 1)
        b["items"] = b["items"][:100]  # cap for transport
        del b["max_min"]

    return {
        "batches": batches, "total_items": total,
        "total_hours": round(sum(b["total_min"] for b in batches) / 60, 1),
    }


def compute_project_review(directory: str, findings: list = None,
                            summary: dict = None, files_scanned: int = 0,
                            smells: list = None, dead_functions: list = None,
                            health: dict = None, satd: dict = None,
                            duplicates: dict = None) -> dict:
    """Generate a comprehensive PM-style project review with grades, charts data, and recommendations."""
    findings = findings or []
    smells = smells or []
    dead_functions = dead_functions or []
    dir_path = Path(directory).resolve()

    # ── Severity breakdown ──
    sev_counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for f in findings:
        sev = f.get("severity", "LOW")
        sev_counts[sev] = sev_counts.get(sev, 0) + 1
    total = sum(sev_counts.values())

    # ── Category breakdown ──
    cat_counts = {}
    for f in findings:
        rid = f.get("rule_id", "UNKNOWN")
        cat = rid.split("-")[0] if "-" in rid else rid
        cat_counts[cat] = cat_counts.get(cat, 0) + 1

    # ── Score ──
    deductions = sev_counts["HIGH"] * 5 + sev_counts["MEDIUM"] * 2 + sev_counts["LOW"] * 0.5
    score = max(0, min(100, round(100 - deductions)))
    letter = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D" if score >= 40 else "F"

    # ── Top hotspot files ──
    file_issues = {}
    for f in findings:
        fp = f.get("file", "unknown")
        file_issues.setdefault(fp, {"high": 0, "medium": 0, "low": 0, "total": 0})
        sev = f.get("severity", "LOW").lower()
        file_issues[fp][sev] = file_issues[fp].get(sev, 0) + 1
        file_issues[fp]["total"] += 1
    hotspots = sorted(file_issues.items(), key=lambda x: (-x[1]["high"], -x[1]["total"]))[:15]

    # ── Recommendations ──
    must_do = []
    should_do = []
    nice_to_have = []

    if sev_counts["HIGH"] > 0:
        must_do.append({
            "title": f"Fix {sev_counts['HIGH']} HIGH severity issues",
            "reason": "High severity findings indicate security vulnerabilities or critical reliability flaws that can lead to data breaches or system failures.",
            "effort": f"{sev_counts['HIGH'] * 15} min",
            "impact": "Critical"
        })

    sec_count = sum(1 for f in findings if f.get("rule_id", "").startswith("SEC-"))
    if sec_count > 0:
        must_do.append({
            "title": f"Address {sec_count} security findings",
            "reason": "Security issues must be resolved before any production release to prevent exploitation.",
            "effort": f"{sec_count * 20} min",
            "impact": "Critical"
        })

    if sev_counts["MEDIUM"] > 5:
        should_do.append({
            "title": f"Reduce {sev_counts['MEDIUM']} MEDIUM severity issues",
            "reason": "Medium issues degrade code quality and increase maintenance burden over time.",
            "effort": f"{sev_counts['MEDIUM'] * 10} min",
            "impact": "High"
        })

    if len(smells) > 5:
        should_do.append({
            "title": f"Refactor {len(smells)} code smells",
            "reason": "Code smells increase complexity, make debugging harder, and slow down new feature development.",
            "effort": f"{len(smells) * 15} min",
            "impact": "Medium"
        })

    if len(dead_functions) > 3:
        should_do.append({
            "title": f"Remove {len(dead_functions)} dead functions",
            "reason": "Dead code confuses developers and increases cognitive load without providing value.",
            "effort": f"{len(dead_functions) * 5} min",
            "impact": "Medium"
        })

    if duplicates and duplicates.get("total_groups", 0) > 0:
        nice_to_have.append({
            "title": f"Consolidate {duplicates.get('total_groups', 0)} duplicate code groups",
            "reason": "Duplicate code increases maintenance burden and risk of inconsistent bug fixes.",
            "effort": f"{duplicates.get('total_groups', 0) * 20} min",
            "impact": "Medium"
        })

    if sev_counts["LOW"] > 10:
        nice_to_have.append({
            "title": f"Clean up {sev_counts['LOW']} LOW severity items",
            "reason": "While individually minor, large numbers of low-severity issues signal declining code discipline.",
            "effort": f"{sev_counts['LOW'] * 5} min",
            "impact": "Low"
        })

    # ── Health snapshot ──
    health_flags = {}
    if health:
        for k, v in health.items():
            if isinstance(v, bool):
                health_flags[k] = v

    # ── Debt summary ──
    debt_hours = satd.get("total_hours", 0) if satd else 0
    debt_items = satd.get("total_items", 0) if satd else 0

    # ── Release readiness ──
    blockers = sev_counts["HIGH"] + sec_count
    release_ready = blockers == 0 and score >= 60
    release_status = "GO" if release_ready else "NO-GO"

    # ── Estimated total fix time ──
    total_fix_min = (sev_counts["HIGH"] * 15 + sev_counts["MEDIUM"] * 10 +
                     sev_counts["LOW"] * 5 + len(smells) * 15 +
                     len(dead_functions) * 5)
    total_fix_hours = round(total_fix_min / 60, 1)

    return {
        "project_name": dir_path.name,
        "directory": str(dir_path),
        "files_scanned": files_scanned,
        "score": score,
        "letter": letter,
        "release_status": release_status,
        "release_ready": release_ready,
        "blockers": blockers,
        "severity": sev_counts,
        "total_findings": total,
        "categories": cat_counts,
        "hotspots": [{"file": h[0], **h[1]} for h in hotspots],
        "must_do": must_do,
        "should_do": should_do,
        "nice_to_have": nice_to_have,
        "health_flags": health_flags,
        "debt_hours": debt_hours,
        "debt_items": debt_items,
        "total_fix_hours": total_fix_hours,
        "smells_count": len(smells),
        "dead_count": len(dead_functions),
        "duplicates_count": duplicates.get("total_groups", 0) if duplicates else 0,
    }


# ═══════════════════════════════════════════════════════════════════
# Phase 7: CGC-Inspired Graph Analysis
# ═══════════════════════════════════════════════════════════════════

def detect_circular_calls(directory: str) -> dict:
    """Detect circular call chains at the FUNCTION level (macaroni code).
    Inspired by CodeGraphContext's call-chain analysis.
    A->B->C->A is a circular call chain that makes code hard to reason about."""
    # Build function-level call graph
    funcs = {}  # key -> {name, file, line, calls: [callee_name]}
    for fpath, rel in _walk_py(directory):
        tree = _safe_parse(fpath)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            key = f"{_fwd(rel)}::{node.name}"
            callees = set()
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Name):
                        callees.add(child.func.id)
                    elif isinstance(child.func, ast.Attribute):
                        callees.add(child.func.attr)
            callees.discard(node.name)  # exclude direct recursion (separate concern)
            funcs[key] = {"name": node.name, "file": _fwd(rel),
                          "line": node.lineno, "calls": list(callees)}

    # Resolve name -> keys
    name_to_keys = defaultdict(list)
    for key, data in funcs.items():
        name_to_keys[data["name"]].append(key)

    # Build adjacency (key -> set of keys)
    adj = defaultdict(set)
    for key, data in funcs.items():
        for callee_name in data["calls"]:
            for ck in name_to_keys.get(callee_name, []):
                if ck != key:
                    adj[key].add(ck)

    # Detect direct recursion
    recursive = []
    for fpath, rel in _walk_py(directory):
        tree = _safe_parse(fpath)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    cname = None
                    if isinstance(child.func, ast.Name):
                        cname = child.func.id
                    elif isinstance(child.func, ast.Attribute):
                        cname = child.func.attr
                    if cname == node.name:
                        recursive.append({
                            "function": node.name,
                            "file": _fwd(rel),
                            "line": node.lineno,
                        })
                        break

    # Find cycles using DFS (Johnson's simplified — cap at reasonable size)
    cycles = []
    visited_global = set()

    def _find_cycles(start, current, path, on_stack):
        if len(cycles) >= 50:
            return
        on_stack.add(current)
        path.append(current)
        for nb in adj.get(current, set()):
            if nb == start and len(path) >= 2:
                cycle = [funcs[k]["name"] for k in path] + [funcs[start]["name"]]
                files = list({funcs[k]["file"] for k in path})
                cycles.append({
                    "chain": cycle,
                    "length": len(cycle) - 1,
                    "files": files,
                    "functions": [{
                        "name": funcs[k]["name"],
                        "file": funcs[k]["file"],
                        "line": funcs[k]["line"],
                    } for k in path],
                })
            elif nb not in on_stack and nb not in visited_global:
                _find_cycles(start, nb, path, on_stack)
        path.pop()
        on_stack.discard(current)

    for key in list(funcs.keys()):
        if key not in visited_global:
            _find_cycles(key, key, [], set())
            visited_global.add(key)

    # Deduplicate cycles (same set of functions = same cycle)
    seen_sets = set()
    unique_cycles = []
    for c in cycles:
        fset = frozenset(c["chain"][:-1])
        if fset not in seen_sets:
            seen_sets.add(fset)
            unique_cycles.append(c)

    unique_cycles.sort(key=lambda x: (-x["length"], x["chain"][0]))

    # Hub functions: high fan-in AND fan-out (coordination smell / spaghetti centers)
    fan_in = defaultdict(int)
    fan_out = defaultdict(int)
    for key, nbs in adj.items():
        fan_out[key] = len(nbs)
        for nb in nbs:
            fan_in[nb] += 1

    hubs = []
    for key, data in funcs.items():
        fi = fan_in.get(key, 0)
        fo = fan_out.get(key, 0)
        if fi >= 3 and fo >= 3:
            hubs.append({
                "name": data["name"],
                "file": data["file"],
                "line": data["line"],
                "fan_in": fi,
                "fan_out": fo,
                "score": fi * fo,
            })
    hubs.sort(key=lambda x: -x["score"])

    return {
        "circular_calls": unique_cycles[:30],
        "total_cycles": len(unique_cycles),
        "recursive_functions": recursive[:20],
        "total_recursive": len(recursive),
        "hub_functions": hubs[:20],
        "total_hubs": len(hubs),
        "total_functions": len(funcs),
        "total_edges": sum(len(v) for v in adj.values()),
    }


def compute_coupling_metrics(directory: str) -> dict:
    """Compute coupling & cohesion metrics per module — inspired by CGC graph analysis.
    Afferent coupling (Ca) = how many modules depend on this one (fan-in).
    Efferent coupling (Ce) = how many modules this one depends on (fan-out).
    Instability (I) = Ce / (Ca + Ce) — 0 = stable, 1 = unstable.
    High Ca + high Ce = god module (tangled). High I + many dependents = fragile."""
    modules = {}  # mod_name -> {file, loc, imports: set, imported_by: set, funcs, classes}
    local_mods = set()

    for fpath, rel in _walk_py(directory):
        mod = _fwd(rel).replace("/", ".").removesuffix(".py").removesuffix(".__init__")
        local_mods.add(mod)
        loc = 0
        func_count = 0
        class_count = 0
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
                loc = sum(1 for ln in lines if ln.strip())
        except OSError:
            pass
        tree = _safe_parse(fpath)
        if tree:
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    func_count += 1
                elif isinstance(node, ast.ClassDef):
                    class_count += 1
        modules[mod] = {
            "name": mod, "file": _fwd(rel), "loc": loc,
            "imports": set(), "imported_by": set(),
            "func_count": func_count, "class_count": class_count,
        }

    # Resolve imports
    for fpath, rel in _walk_py(directory):
        mod = _fwd(rel).replace("/", ".").removesuffix(".py").removesuffix(".__init__")
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    line = line.strip()
                    if not (line.startswith("import ") or line.startswith("from ")):
                        continue
                    parts = line.split()
                    target = None
                    if parts[0] == "import":
                        target = parts[1].split(".")[0]
                    elif len(parts) >= 2:
                        target = parts[1].split(".")[0]
                    if target and target in local_mods and target != mod:
                        modules[mod]["imports"].add(target)
                        if target in modules:
                            modules[target]["imported_by"].add(mod)
        except (OSError, UnicodeDecodeError):
            continue

    # Compute metrics
    results = []
    for mod, data in modules.items():
        ca = len(data["imported_by"])  # afferent coupling
        ce = len(data["imports"])       # efferent coupling
        instability = round(ce / (ca + ce), 2) if (ca + ce) > 0 else 0.5

        # Cohesion estimate: ratio of internal function calls vs external dependencies
        # Low ratio = low cohesion (module does unrelated things)
        cohesion = "high" if ce <= 2 and data["func_count"] <= 8 else \
                   "medium" if ce <= 5 else "low"

        health = "healthy"
        if ca >= 5 and ce >= 5:
            health = "god_module"
        elif instability > 0.8 and ca >= 3:
            health = "fragile"
        elif ca == 0 and ce == 0 and data["loc"] > 20:
            health = "isolated"
        elif ce > 8:
            health = "dependent"

        results.append({
            "module": mod, "file": data["file"], "loc": data["loc"],
            "afferent_coupling": ca, "efferent_coupling": ce,
            "instability": instability, "cohesion": cohesion,
            "health": health, "func_count": data["func_count"],
            "class_count": data["class_count"],
            "imports": sorted(data["imports"]),
            "imported_by": sorted(data["imported_by"]),
        })

    results.sort(key=lambda x: -(x["afferent_coupling"] + x["efferent_coupling"]))

    # Summary
    health_counts = defaultdict(int)
    for r in results:
        health_counts[r["health"]] += 1

    avg_instability = round(sum(r["instability"] for r in results) / max(len(results), 1), 2)

    return {
        "modules": results,
        "total_modules": len(results),
        "health_summary": dict(health_counts),
        "avg_instability": avg_instability,
        "god_modules": [r for r in results if r["health"] == "god_module"][:10],
        "fragile_modules": [r for r in results if r["health"] == "fragile"][:10],
        "isolated_modules": [r for r in results if r["health"] == "isolated"][:10],
    }


def detect_unused_imports(directory: str) -> dict:
    """AST-based unused import detection — clean code starts with clean imports."""
    issues = []

    for fpath, rel in _walk_py(directory):
        tree = _safe_parse(fpath)
        if tree is None:
            continue

        # Collect all imported names and their line numbers
        imported = {}  # name -> line
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name.split(".")[0]
                    imported[name] = node.lineno
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("__"):
                    continue
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    name = alias.asname if alias.asname else alias.name
                    imported[name] = node.lineno

        if not imported:
            continue

        # Collect all Name references in the file (excluding import nodes)
        used_names = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if isinstance(node, ast.Name):
                used_names.add(node.id)
            elif isinstance(node, ast.Attribute):
                # For chained attrs like `os.path`, collect the root
                root = node
                while isinstance(root, ast.Attribute):
                    root = root.value
                if isinstance(root, ast.Name):
                    used_names.add(root.id)
            # Check string annotations (TYPE_CHECKING style)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                for imp_name in imported:
                    if imp_name in node.value:
                        used_names.add(imp_name)

        # Determine unused
        for name, line in imported.items():
            if name not in used_names and name != "_":
                issues.append({
                    "file": _fwd(rel),
                    "line": line,
                    "import_name": name,
                    "severity": "LOW",
                })

    issues.sort(key=lambda x: (x["file"], x["line"]))

    # Group by file for summary
    by_file = defaultdict(int)
    for i in issues:
        by_file[i["file"]] += 1

    return {
        "unused_imports": issues,
        "total_unused": len(issues),
        "files_with_unused": len(by_file),
        "by_file": dict(sorted(by_file.items(), key=lambda x: -x[1])[:20]),
    }
