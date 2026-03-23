"""
Analysis API routes — all analyzer-delegating POST endpoints.
"""

import os
from pathlib import Path

from services.git_analyzer import analyze_git_hotspots, parse_imports, run_ruff
from services.satd_scanner import scan_satd


def _dir_from_body(body: dict) -> tuple[str | None, dict | None]:
    """Extract and validate directory from request body. Returns (resolved_dir, error_response)."""
    directory = body.get("directory", "")
    if not directory or not os.path.isdir(directory):
        return None, {"error": f"Invalid directory: {directory}"}
    return str(Path(directory).resolve()), None


def handle_satd(body, handler):
    d, err = _dir_from_body(body)
    if err:
        return err, 400
    return scan_satd(d), 200


def handle_git_hotspots(body, handler):
    d, err = _dir_from_body(body)
    if err:
        return err, 400
    return analyze_git_hotspots(d, body.get("days", 90)), 200


def handle_imports(body, handler):
    d, err = _dir_from_body(body)
    if err:
        return err, 400
    return parse_imports(d), 200


def handle_ruff(body, handler):
    d, err = _dir_from_body(body)
    if err:
        return err, 400
    return run_ruff(d), 200


def handle_format(body, handler):
    from analyzers import check_format

    d, err = _dir_from_body(body)
    if err:
        return err, 400
    return check_format(d), 200


def handle_typecheck(body, handler):
    from analyzers import check_types

    d, err = _dir_from_body(body)
    if err:
        return err, 400
    return check_types(d), 200


def handle_health(body, handler):
    from analyzers import check_project_health

    d, err = _dir_from_body(body)
    if err:
        return err, 400
    return check_project_health(d), 200


def handle_bandit(body, handler):
    from analyzers import run_bandit

    d, err = _dir_from_body(body)
    if err:
        return err, 400
    return run_bandit(d), 200


def handle_dead_code(body, handler):
    from analyzers import detect_dead_functions

    d, err = _dir_from_body(body)
    if err:
        return err, 400
    return detect_dead_functions(d), 200


def handle_smells(body, handler):
    from analyzers import detect_code_smells

    d, err = _dir_from_body(body)
    if err:
        return err, 400
    return detect_code_smells(d), 200


def handle_duplicates(body, handler):
    from analyzers import detect_duplicates

    d, err = _dir_from_body(body)
    if err:
        return err, 400
    return detect_duplicates(d), 200


def handle_temporal_coupling(body, handler):
    from analyzers import analyze_temporal_coupling

    d, err = _dir_from_body(body)
    if err:
        return err, 400
    return analyze_temporal_coupling(d, body.get("days", 90)), 200


def handle_typecheck_pyright(body, handler):
    from analyzers import run_typecheck

    d, err = _dir_from_body(body)
    if err:
        return err, 400
    return run_typecheck(d), 200


def handle_release_readiness(body, handler):
    from analyzers import check_release_readiness

    d, err = _dir_from_body(body)
    if err:
        return err, 400
    return check_release_readiness(d), 200


def handle_ai_detect(body, handler):
    from analyzers import detect_ai_code

    d, err = _dir_from_body(body)
    if err:
        return err, 400
    return detect_ai_code(d), 200


def handle_web_smells(body, handler):
    from analyzers import detect_web_smells

    d, err = _dir_from_body(body)
    if err:
        return err, 400
    return detect_web_smells(d), 200


def handle_connection_test(body, handler):
    from analyzers import analyze_connections

    d, err = _dir_from_body(body)
    if err:
        return err, 400
    return analyze_connections(d), 200


def handle_test_gen(body, handler):
    from analyzers import generate_test_stubs

    d, err = _dir_from_body(body)
    if err:
        return err, 400
    return generate_test_stubs(d), 200


def handle_remediation_time(body, handler):
    from analyzers import estimate_remediation_time

    findings = body.get("findings", [])
    return estimate_remediation_time(findings), 200


POST_ROUTES = {
    "/api/satd": handle_satd,
    "/api/git-hotspots": handle_git_hotspots,
    "/api/imports": handle_imports,
    "/api/ruff": handle_ruff,
    "/api/format": handle_format,
    "/api/typecheck": handle_typecheck,
    "/api/health": handle_health,
    "/api/bandit": handle_bandit,
    "/api/dead-code": handle_dead_code,
    "/api/smells": handle_smells,
    "/api/duplicates": handle_duplicates,
    "/api/temporal-coupling": handle_temporal_coupling,
    "/api/typecheck-pyright": handle_typecheck_pyright,
    "/api/release-readiness": handle_release_readiness,
    "/api/ai-detect": handle_ai_detect,
    "/api/web-smells": handle_web_smells,
    "/api/connection-test": handle_connection_test,
    "/api/test-gen": handle_test_gen,
    "/api/remediation-time": handle_remediation_time,
}
