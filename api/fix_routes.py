"""
Fix API routes — /api/preview-fix, /api/apply-fix, /api/apply-fixes-bulk.
"""


def handle_preview_fix(body: dict, handler) -> tuple[dict, int]:
    from xray.fixer import preview_fix

    return preview_fix(body), 200


def handle_apply_fix(body: dict, handler) -> tuple[dict, int]:
    from xray.fixer import apply_fix

    return apply_fix(body), 200


def handle_apply_fixes_bulk(body: dict, handler) -> tuple[dict, int]:
    from xray.fixer import apply_fixes_bulk

    findings = body.get("findings", [])
    return apply_fixes_bulk(findings), 200


POST_ROUTES = {
    "/api/preview-fix": handle_preview_fix,
    "/api/apply-fix": handle_apply_fix,
    "/api/apply-fixes-bulk": handle_apply_fixes_bulk,
}
