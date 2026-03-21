"""
X-Ray LLM — Python & dependency version verification + API compatibility.

Validates that:
  1. The running Python version meets the minimum (3.10).
  2. Installed libraries meet minimum version requirements.
  3. The specific library APIs (classes, methods, attributes) that X-Ray
     actually calls still exist in the installed versions — catching renames,
     deprecations, and breaking changes after library upgrades.

Usage:
    from xray.compat import check_environment
    ok, problems = check_environment()       # returns (bool, list[str])

    from xray.compat import check_api_compatibility
    report = check_api_compatibility()       # returns list[APICheckResult]
"""

import importlib
import importlib.metadata
import logging
import sys

logger = logging.getLogger(__name__)

# ── Minimum Python version ───────────────────────────────────────────────
MIN_PYTHON = (3, 10)

# ── Dependency table ─────────────────────────────────────────────────────
# (package_name, min_version_tuple, import_name, required)
#   required=True  → hard dependency, blocks startup
#   required=False → optional, warn only
DEPENDENCIES: list[tuple[str, tuple[int, ...], str, bool]] = [
    ("pytest",            (7, 0),       "pytest",     True),
    ("llama-cpp-python",  (0, 3, 0),    "llama_cpp",  False),
    ("requests",          (2, 30),      "requests",   False),
    ("flet",              (0, 25),      "flet",       False),
    ("ruff",              (0, 15),      "ruff",       False),
    ("bandit",            (1, 9),       "bandit",     False),
]


def _parse_version(version_str: str) -> tuple[int, ...]:
    """Parse '1.2.3' or '1.2.3rc1' into (1, 2, 3)."""
    parts: list[int] = []
    for segment in version_str.split("."):
        # Strip non-numeric suffixes like 'rc1', 'a2', 'post1'
        digits = ""
        for ch in segment:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits:
            parts.append(int(digits))
    return tuple(parts)


def _version_gte(installed: tuple[int, ...], minimum: tuple[int, ...]) -> bool:
    """True if *installed* >= *minimum* with implicit zero-padding."""
    length = max(len(installed), len(minimum))
    a = installed + (0,) * (length - len(installed))
    b = minimum + (0,) * (length - len(minimum))
    return a >= b


def _fmt(ver: tuple[int, ...]) -> str:
    return ".".join(str(v) for v in ver)


# ── Public API ───────────────────────────────────────────────────────────

def check_python_version() -> list[str]:
    """Return problems (empty list = OK) for the running Python version."""
    current = sys.version_info[:3]
    if current < MIN_PYTHON:
        return [
            f"Python {_fmt(current)} is too old — "
            f"X-Ray LLM requires Python >= {_fmt(MIN_PYTHON)}"
        ]
    return []


def check_dependency(pkg_name: str, min_version: tuple[int, ...]) -> str | None:
    """Return an error string if *pkg_name* is missing or too old, else None."""
    try:
        meta = importlib.metadata.metadata(pkg_name)
    except importlib.metadata.PackageNotFoundError:
        return f"{pkg_name} is not installed (need >= {_fmt(min_version)})"

    installed_str = meta["Version"]
    installed = _parse_version(installed_str)
    if not _version_gte(installed, min_version):
        return (
            f"{pkg_name} {installed_str} is too old "
            f"(need >= {_fmt(min_version)})"
        )
    return None


def check_environment(*, warn_optional: bool = True) -> tuple[bool, list[str]]:
    """Verify Python version, all dependencies, and API compatibility.

    Returns:
        (ok, problems) — *ok* is False only for hard-requirement failures
        or broken API symbols.  Optional-dependency issues and uninstalled
        libraries appear in *problems* as warnings but don't set *ok* to False.
    """
    problems: list[str] = []
    ok = True

    # 1. Python version
    py_issues = check_python_version()
    if py_issues:
        problems.extend(py_issues)
        ok = False

    # 2. Dependencies
    for pkg_name, min_ver, _import_name, required in DEPENDENCIES:
        issue = check_dependency(pkg_name, min_ver)
        if issue:
            if required:
                problems.append(f"[REQUIRED] {issue}")
                ok = False
            elif warn_optional:
                problems.append(f"[optional] {issue}")

    # 3. API compatibility — verify the symbols we call still exist
    api_results = check_api_compatibility()
    for r in api_results:
        if not r.found and r.error != "library not installed":
            problems.append(
                f"[API BREAK] {r.import_path}.{r.attr_chain} — "
                f"{r.error} (used in {r.used_in})"
            )
            ok = False

    return ok, problems


def require_environment() -> None:
    """Check environment and exit with a clear message if it fails."""
    ok, problems = check_environment()
    if problems:
        for p in problems:
            level = logging.ERROR if p.startswith("[REQUIRED]") or "too old" in p.lower() and "Python" in p else logging.WARNING
            logger.log(level, p)
    if not ok:
        sys.exit(
            "\n".join(
                [
                    "",
                    "=" * 60,
                    "  X-Ray LLM — Environment Check FAILED",
                    "=" * 60,
                    "",
                    *[f"  • {p}" for p in problems if p.startswith("[REQUIRED]") or "Python" in p],
                    "",
                    "  Run: pip install -r requirements.txt",
                    "  Required Python: >= 3.10",
                    "=" * 60,
                ]
            )
        )


def environment_summary() -> str:
    """Return a human-readable summary of the current environment."""
    lines = [
        f"Python {_fmt(sys.version_info[:3])} "
        f"({'OK' if sys.version_info[:2] >= MIN_PYTHON else 'TOO OLD'})",
    ]
    for pkg_name, min_ver, _import_name, required in DEPENDENCIES:
        try:
            meta = importlib.metadata.metadata(pkg_name)
            installed_str = meta["Version"]
            installed = _parse_version(installed_str)
            status = "OK" if _version_gte(installed, min_ver) else "UPGRADE"
        except importlib.metadata.PackageNotFoundError:
            installed_str = "—"
            status = "MISSING"

        tag = "req" if required else "opt"
        lines.append(f"  {pkg_name:25s} {installed_str:15s} >= {_fmt(min_ver):10s} [{tag}] {status}")

    return "\n".join(lines)


# ── API Compatibility Checker ────────────────────────────────────────────
#
# For every third-party library we use, we register the *exact* symbols
# (classes, methods, attributes) that our code calls.  At verification
# time we import the library and confirm each symbol is reachable via
# getattr chains.  This catches:
#   • APIs removed in newer library versions
#   • Renamed classes / methods after major upgrades
#   • Missing attributes that would only surface at runtime
#
# Each entry:  (import_path, attr_chain, used_in_file, description)
#   import_path  — the top-level module to import (e.g. "llama_cpp")
#   attr_chain   — dot-separated path to resolve (e.g. "Llama.create_chat_completion")
#   used_in_file — where we use it (for diagnostics)
#   description  — human note on what this is for

API_REGISTRY: list[tuple[str, str, str, str]] = [
    # ── llama-cpp-python ─────────────────────────────────────────────
    ("llama_cpp", "Llama",
     "xray/llm.py", "Core LLM class for model loading"),
    ("llama_cpp", "Llama.create_chat_completion",
     "xray/llm.py", "Chat completion API used for code generation"),

    # ── pytest (core API surface we rely on) ─────────────────────────
    ("pytest", "fixture",
     "tests/", "Decorator for test fixtures"),
    ("pytest", "mark.parametrize",
     "tests/", "Parametrized test decorator"),
    ("pytest", "raises",
     "tests/", "Exception assertion context manager"),
    ("pytest", "skip",
     "tests/", "Conditional test skip"),
    ("pytest", "fail",
     "tests/", "Explicit test failure"),

    # ── requests ─────────────────────────────────────────────────────
    ("requests", "get",
     "xray/wire_connector.py", "HTTP GET for endpoint testing"),
    ("requests", "post",
     "xray/wire_connector.py", "HTTP POST for endpoint testing"),
    ("requests", "Response",
     "xray/wire_connector.py", "Response class (status_code, text, headers)"),
]


class APICheckResult:
    """Result of checking one API symbol."""

    __slots__ = ("import_path", "attr_chain", "used_in", "description",
                 "found", "error")

    def __init__(self, import_path: str, attr_chain: str, used_in: str,
                 description: str, found: bool, error: str = ""):
        self.import_path = import_path
        self.attr_chain = attr_chain
        self.used_in = used_in
        self.description = description
        self.found = found
        self.error = error

    def __repr__(self) -> str:
        status = "OK" if self.found else f"MISSING ({self.error})"
        return f"{self.import_path}.{self.attr_chain}: {status}"


def _resolve_attr_chain(module: object, chain: str) -> tuple[bool, str]:
    """Walk a dot-separated attribute chain on *module*.

    Returns (True, "") on success or (False, error_message) on failure.
    """
    obj = module
    parts = chain.split(".")
    for i, part in enumerate(parts):
        if not hasattr(obj, part):
            resolved_so_far = ".".join(parts[:i]) if i else "(root)"
            return False, f"'{part}' not found on {resolved_so_far}"
        obj = getattr(obj, part)
    return True, ""


def check_api_compatibility() -> list[APICheckResult]:
    """Verify every registered API symbol is reachable.

    Skips libraries that aren't installed (those are caught by the
    version checker already).  Returns a list of APICheckResult for
    each registered entry.
    """
    results: list[APICheckResult] = []

    for import_path, attr_chain, used_in, description in API_REGISTRY:
        try:
            mod = importlib.import_module(import_path)
        except ImportError:
            # Library not installed — already flagged by version check
            results.append(APICheckResult(
                import_path, attr_chain, used_in, description,
                found=False, error="library not installed",
            ))
            continue

        found, error = _resolve_attr_chain(mod, attr_chain)
        results.append(APICheckResult(
            import_path, attr_chain, used_in, description,
            found=found, error=error,
        ))

    return results


def api_compatibility_summary() -> str:
    """Human-readable report of API compatibility checks."""
    results = check_api_compatibility()
    if not results:
        return "No API checks registered."

    lines: list[str] = []
    ok_count = sum(1 for r in results if r.found)
    fail_count = len(results) - ok_count
    skip_count = sum(1 for r in results if r.error == "library not installed")

    lines.append(f"API compatibility: {ok_count} OK, {fail_count} issues"
                 + (f" ({skip_count} skipped — not installed)" if skip_count else ""))

    # Group by library
    by_lib: dict[str, list[APICheckResult]] = {}
    for r in results:
        by_lib.setdefault(r.import_path, []).append(r)

    for lib, checks in sorted(by_lib.items()):
        lib_ok = all(c.found for c in checks)
        lines.append(f"\n  {lib} {'✓' if lib_ok else '✗'}")
        for c in checks:
            mark = "OK" if c.found else f"MISSING: {c.error}"
            lines.append(f"    .{c.attr_chain:40s} [{mark}]  ({c.used_in})")

    broken = [r for r in results if not r.found and r.error != "library not installed"]
    if broken:
        lines.append("\n  ⚠ BREAKING CHANGES DETECTED:")
        for r in broken:
            lines.append(f"    {r.import_path}.{r.attr_chain} — {r.error}")
            lines.append(f"      Used in: {r.used_in} — {r.description}")

    return "\n".join(lines)
