"""
Scan API routes — /api/scan, /api/scan-progress, /api/scan-result, /api/abort.
"""

import os
import threading
from pathlib import Path

from services.app_state import state
from services.scan_manager import (
    background_scan, count_scannable_files,
)


def handle_scan(body: dict, handler) -> tuple[dict, int]:
    directory = body.get("directory", "")
    engine = body.get("engine", "python")
    severity = body.get("severity", "LOW")
    excludes = body.get("excludes", [])

    if not directory or not os.path.isdir(directory):
        return {"error": f"Invalid directory: {directory}"}, 400

    directory = str(Path(directory).resolve())
    state.reset_scan()

    total = count_scannable_files(directory, excludes)

    state.abort.clear()
    t = threading.Thread(
        target=background_scan,
        args=(directory, engine, severity, excludes, total),
        daemon=True,
    )
    t.start()
    state.scan_thread = t

    return {"status": "started", "total_files": total}, 200


def handle_abort(body: dict, handler) -> tuple[dict, int]:
    state.abort.set()
    with state.rust_proc_lock:
        if state.rust_proc and state.rust_proc.poll() is None:
            state.rust_proc.kill()
    return {"ok": True}, 200


def handle_scan_result(params: dict, handler) -> tuple[dict, int]:
    if state.last_scan_result is not None:
        return state.last_scan_result, 200
    return {"error": "No scan results available"}, 404


def handle_scan_progress(params: dict, handler) -> tuple[dict, int]:
    if state.scan_progress is not None:
        return state.scan_progress, 200
    return {"status": "idle"}, 200


GET_ROUTES = {
    "/api/scan-result": handle_scan_result,
    "/api/scan-progress": handle_scan_progress,
}

POST_ROUTES = {
    "/api/scan": handle_scan,
    "/api/abort": handle_abort,
}
