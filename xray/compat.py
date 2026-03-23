"""
X-Ray LLM — Python & dependency version verification + API compatibility.

Validates that:
  1. The running Python version meets the minimum (3.10).
  2. Installed libraries meet minimum version requirements.
  3. The specific library APIs (classes, methods, attributes) that X-Ray
     actually calls still exist in the installed versions — catching renames,
     deprecations, and breaking changes after library upgrades.
  4. Compares installed versions against PyPI latest + analyses upgrade
     impact on the APIs we actually use.

Usage:
    from xray.compat import check_environment
    ok, problems = check_environment()       # returns (bool, list[str])

    from xray.compat import check_api_compatibility
    report = check_api_compatibility()       # returns list[APICheckResult]

    from xray.compat import check_dependency_freshness
    report = check_dependency_freshness()    # returns list[DependencyStatus]
"""

import importlib
import importlib.metadata
import json
import logging
import sys
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

# ── Minimum Python version ───────────────────────────────────────────────
MIN_PYTHON = (3, 10)

# ── Dependency table ─────────────────────────────────────────────────────
# (package_name, min_version_tuple, import_name, required)
#   required=True  → hard dependency, blocks startup
#   required=False → optional, warn only
DEPENDENCIES: list[tuple[str, tuple[int, ...], str, bool]] = [
    ("pytest", (7, 0), "pytest", True),
    ("llama-cpp-python", (0, 3, 0), "llama_cpp", False),
    ("requests", (2, 30), "requests", False),
    ("flet", (0, 25), "flet", False),
    ("ruff", (0, 15), "ruff", False),
    ("bandit", (1, 9), "bandit", False),
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
        return [f"Python {_fmt(current)} is too old — X-Ray LLM requires Python >= {_fmt(MIN_PYTHON)}"]
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
        return f"{pkg_name} {installed_str} is too old (need >= {_fmt(min_version)})"
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
            problems.append(f"[API BREAK] {r.import_path}.{r.attr_chain} — {r.error} (used in {r.used_in})")
            ok = False

    return ok, problems


def require_environment() -> None:
    """Check environment and exit with a clear message if it fails."""
    ok, problems = check_environment()
    if problems:
        for p in problems:
            level = (
                logging.ERROR
                if p.startswith("[REQUIRED]") or ("too old" in p.lower() and "Python" in p)
                else logging.WARNING
            )
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
        f"Python {_fmt(sys.version_info[:3])} ({'OK' if sys.version_info[:2] >= MIN_PYTHON else 'TOO OLD'})",
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
    ("llama_cpp", "Llama", "xray/llm.py", "Core LLM class for model loading"),
    ("llama_cpp", "Llama.create_chat_completion", "xray/llm.py", "Chat completion API used for code generation"),
    # ── pytest (core API surface we rely on) ─────────────────────────
    ("pytest", "fixture", "tests/", "Decorator for test fixtures"),
    ("pytest", "mark.parametrize", "tests/", "Parametrized test decorator"),
    ("pytest", "raises", "tests/", "Exception assertion context manager"),
    ("pytest", "skip", "tests/", "Conditional test skip"),
    ("pytest", "fail", "tests/", "Explicit test failure"),
    # ── requests ─────────────────────────────────────────────────────
    ("requests", "get", "xray/wire_connector.py", "HTTP GET for endpoint testing"),
    ("requests", "post", "xray/wire_connector.py", "HTTP POST for endpoint testing"),
    ("requests", "Response", "xray/wire_connector.py", "Response class (status_code, text, headers)"),
]


class APICheckResult:
    """Result of checking one API symbol."""

    __slots__ = (
        "attr_chain",
        "description",
        "error",
        "found",
        "import_path",
        "used_in",
    )

    def __init__(self, import_path: str, attr_chain: str, used_in: str, description: str, found: bool, error: str = ""):
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
            results.append(
                APICheckResult(
                    import_path,
                    attr_chain,
                    used_in,
                    description,
                    found=False,
                    error="library not installed",
                )
            )
            continue

        found, error = _resolve_attr_chain(mod, attr_chain)
        results.append(
            APICheckResult(
                import_path,
                attr_chain,
                used_in,
                description,
                found=found,
                error=error,
            )
        )

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

    lines.append(
        f"API compatibility: {ok_count} OK, {fail_count} issues"
        + (f" ({skip_count} skipped — not installed)" if skip_count else "")
    )

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


# ── PyPI Version Fetcher ─────────────────────────────────────────────────


def _fetch_pypi_version(package_name: str, timeout: int = 5) -> str | None:
    """Query PyPI JSON API for the latest stable version of *package_name*.

    Returns the version string or None on failure.  Only considers stable
    releases (skips pre-releases like a/b/rc/dev).
    """
    url = f"https://pypi.org/pypi/{package_name}/json"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})  # noqa: S310
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            data = json.loads(resp.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
        return None

    latest = data.get("info", {}).get("version")
    if latest:
        return latest

    # Fallback: find newest stable release from releases dict
    releases = data.get("releases", {})
    stable = []
    for ver_str in releases:
        lo = ver_str.lower()
        if any(tag in lo for tag in ("a", "b", "rc", "dev", "alpha", "beta")):
            continue
        stable.append((_parse_version(ver_str), ver_str))
    if stable:
        stable.sort(reverse=True)
        return stable[0][1]
    return None


# ── Dependency Freshness Checker ─────────────────────────────────────────


class DependencyStatus:
    """Full status of one dependency: installed vs latest vs API impact."""

    __slots__ = (
        "api_symbols_broken",
        "api_symbols_ok",
        "api_symbols_used",
        "error",
        "import_name",
        "installed_version",
        "is_major_upgrade",
        "is_outdated",
        "latest_version",
        "min_version",
        "package",
        "required",
        "upgrade_risk",
    )

    def __init__(self, package: str, import_name: str, required: bool):
        self.package = package
        self.import_name = import_name
        self.required = required
        self.installed_version: str = ""
        self.min_version: str = ""
        self.latest_version: str = ""
        self.is_outdated: bool = False
        self.is_major_upgrade: bool = False
        self.api_symbols_used: list[str] = []
        self.api_symbols_ok: list[str] = []
        self.api_symbols_broken: list[str] = []
        self.upgrade_risk: str = "unknown"  # low / medium / high / unknown
        self.error: str = ""

    def to_dict(self) -> dict:
        return {
            "package": self.package,
            "import_name": self.import_name,
            "required": self.required,
            "installed_version": self.installed_version,
            "min_version": self.min_version,
            "latest_version": self.latest_version,
            "is_outdated": self.is_outdated,
            "is_major_upgrade": self.is_major_upgrade,
            "api_symbols_used": self.api_symbols_used,
            "api_symbols_ok": self.api_symbols_ok,
            "api_symbols_broken": self.api_symbols_broken,
            "upgrade_risk": self.upgrade_risk,
            "error": self.error,
        }


def _is_major_upgrade(installed: str, latest: str) -> bool:
    """True if the major version changed between installed and latest."""
    inst = _parse_version(installed)
    lat = _parse_version(latest)
    if not inst or not lat:
        return False
    return inst[0] != lat[0]


def check_dependency_freshness(
    *,
    timeout: int = 5,
) -> list[DependencyStatus]:
    """Check all registered dependencies against PyPI and API registry.

    For each dependency in DEPENDENCIES:
      1. Get installed version from importlib.metadata
      2. Fetch latest version from PyPI
      3. Cross-reference with API_REGISTRY to list symbols we use
      4. Verify each symbol still exists (current install)
      5. Assess upgrade risk

    Returns a list of DependencyStatus objects.
    """
    # Build a lookup: import_name → list of (attr_chain, used_in)
    api_by_import: dict[str, list[tuple[str, str]]] = {}
    for import_path, attr_chain, used_in, _desc in API_REGISTRY:
        api_by_import.setdefault(import_path, []).append((attr_chain, used_in))

    results: list[DependencyStatus] = []

    for pkg_name, min_ver, import_name, required in DEPENDENCIES:
        status = DependencyStatus(pkg_name, import_name, required)
        status.min_version = _fmt(min_ver)

        # 1. Installed version
        try:
            meta = importlib.metadata.metadata(pkg_name)
            status.installed_version = meta["Version"] or ""
        except importlib.metadata.PackageNotFoundError:
            status.installed_version = ""
            status.error = "not installed"
            status.upgrade_risk = "unknown"
            results.append(status)
            continue

        # 2. Latest from PyPI
        latest = _fetch_pypi_version(pkg_name, timeout=timeout)
        status.latest_version = latest or ""

        if latest:
            inst_tuple = _parse_version(status.installed_version)
            lat_tuple = _parse_version(latest)
            status.is_outdated = not _version_gte(inst_tuple, lat_tuple)
            status.is_major_upgrade = _is_major_upgrade(status.installed_version, latest)

        # 3. API symbols cross-reference
        symbols = api_by_import.get(import_name, [])
        status.api_symbols_used = [chain for chain, _used in symbols]

        # 4. Verify current symbols
        try:
            mod = importlib.import_module(import_name)
            for chain, _used_in in symbols:
                found, _err = _resolve_attr_chain(mod, chain)
                if found:
                    status.api_symbols_ok.append(chain)
                else:
                    status.api_symbols_broken.append(chain)
        except ImportError:
            status.api_symbols_broken = [chain for chain, _ in symbols]

        # 5. Assess upgrade risk
        if not status.is_outdated:
            status.upgrade_risk = "none"
        elif status.api_symbols_broken or status.is_major_upgrade:
            status.upgrade_risk = "high"
        elif status.is_outdated and status.api_symbols_used:
            status.upgrade_risk = "medium"
        elif status.is_outdated:
            status.upgrade_risk = "low"

        results.append(status)

    return results


def dependency_freshness_summary(
    statuses: list[DependencyStatus] | None = None,
) -> dict:
    """Return a structured summary for the UI / API endpoint.

    Returns:
        {
            "dependencies": [...],
            "summary": {
                "total": N,
                "up_to_date": N,
                "outdated": N,
                "major_upgrades": N,
                "broken_apis": N,
                "not_installed": N,
            }
        }
    """
    if statuses is None:
        statuses = check_dependency_freshness()

    deps = [s.to_dict() for s in statuses]
    return {
        "dependencies": deps,
        "summary": {
            "total": len(statuses),
            "up_to_date": sum(1 for s in statuses if not s.is_outdated and not s.error),
            "outdated": sum(1 for s in statuses if s.is_outdated),
            "major_upgrades": sum(1 for s in statuses if s.is_major_upgrade),
            "broken_apis": sum(1 for s in statuses if s.api_symbols_broken),
            "not_installed": sum(1 for s in statuses if s.error == "not installed"),
        },
    }
