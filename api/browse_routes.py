"""
Browse / info / env API routes.
"""

import platform
from pathlib import Path

from services.scan_manager import _fwd, browse_directory, get_drives, get_rust_binary


def handle_browse(params: dict, handler) -> tuple[dict, int]:
    dir_path = params.get("path", [""])[0] if isinstance(params.get("path"), list) else params.get("path", "")
    if not dir_path:
        return {"drives": get_drives()}, 200
    return browse_directory(dir_path), 200


def handle_info(params: dict, handler) -> tuple[dict, int]:
    rust_bin = get_rust_binary()
    from xray.fixer import FIXABLE_RULES
    return {
        "platform": f"{platform.system()} {platform.machine()}",
        "python": platform.python_version(),
        "rust_available": rust_bin is not None,
        "rust_binary": rust_bin,
        "rules_count": len(__import__("xray.rules", fromlist=["ALL_RULES"]).ALL_RULES),
        "home": _fwd(str(Path.home())),
        "fixable_rules": sorted(FIXABLE_RULES),
    }, 200


def handle_env_check(params: dict, handler) -> tuple[dict, int]:
    from xray.compat import (
        check_environment, environment_summary,
        check_api_compatibility, api_compatibility_summary,
        DEPENDENCIES, MIN_PYTHON,
    )
    ok, problems = check_environment()
    api_results = check_api_compatibility()
    api_report = [
        {
            "library": r.import_path, "symbol": r.attr_chain,
            "used_in": r.used_in, "description": r.description,
            "found": r.found, "error": r.error,
        }
        for r in api_results
    ]
    return {
        "ok": ok,
        "python_version": platform.python_version(),
        "min_python": ".".join(str(v) for v in MIN_PYTHON),
        "problems": problems,
        "summary": environment_summary(),
        "api_compatibility": api_report,
        "api_summary": api_compatibility_summary(),
    }, 200


def handle_dependency_check(params: dict, handler) -> tuple[dict, int]:
    from xray.compat import dependency_freshness_summary
    return dependency_freshness_summary(), 200


GET_ROUTES = {
    "/api/browse": handle_browse,
    "/api/info": handle_info,
    "/api/env-check": handle_env_check,
    "/api/dependency-check": handle_dependency_check,
}
