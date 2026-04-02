"""
Transpile API routes — /api/transpile-file, /api/transpile-directory,
/api/transpile-pipeline, /api/transpile-status.
"""

import os
import threading
from pathlib import Path

# ── Shared transpile state ───────────────────────────────────────────────

_transpile_lock = threading.Lock()
_transpile_status: dict = {
    "running": False,
    "phase": "",
    "progress": 0,
    "result": None,
    "error": None,
}


def _reset_status():
    _transpile_status.update(
        running=False, phase="", progress=0, result=None, error=None,
    )


def _status_snapshot() -> dict:
    with _transpile_lock:
        return dict(_transpile_status)


def _run_transpile(mode: str, target: str, config_overrides: dict):
    """Background worker for transpilation."""
    from xray.transpiler import TranspileConfig, Transpiler

    with _transpile_lock:
        _transpile_status["running"] = True
        _transpile_status["phase"] = "initializing"
        _transpile_status["progress"] = 0
        _transpile_status["result"] = None
        _transpile_status["error"] = None

    try:
        cfg = TranspileConfig(
            output_dir=config_overrides.get("output_dir", "rust_output"),
            crate_name=config_overrides.get("crate_name", "transpiled"),
            use_llm=config_overrides.get("use_llm", False),
        )
        t = Transpiler(cfg)

        with _transpile_lock:
            _transpile_status["phase"] = "transpiling"
            _transpile_status["progress"] = 10

        if mode == "file":
            result = t.transpile_file(target)
        elif mode == "directory":
            result = t.transpile_directory(target)
        elif mode == "pipeline":
            result = t.full_pipeline(target)
        else:
            raise ValueError(f"Unknown mode: {mode}")

        with _transpile_lock:
            _transpile_status["phase"] = "complete"
            _transpile_status["progress"] = 100
            _transpile_status["result"] = {
                "modules_transpiled": result.modules_transpiled,
                "files_written": list(result.files_written.keys()),
                "compile_success": result.compile_success,
                "compile_errors": result.compile_errors[:50],
                "warnings": result.warnings[:50],
                "llm_calls_made": result.llm_calls_made,
            }
            _transpile_status["running"] = False

    except Exception as exc:
        with _transpile_lock:
            _transpile_status["phase"] = "error"
            _transpile_status["error"] = str(exc)
            _transpile_status["running"] = False


# ── Route handlers ───────────────────────────────────────────────────────


def handle_transpile_file(body: dict, handler) -> tuple[dict, int]:
    filepath = body.get("file", "")
    if not filepath or not os.path.isfile(filepath):
        return {"error": f"Invalid file: {filepath}"}, 400

    if _transpile_status.get("running"):
        return {"error": "Transpilation already in progress"}, 409

    cfg = body.get("config", {})
    t = threading.Thread(
        target=_run_transpile,
        args=("file", str(Path(filepath).resolve()), cfg),
        daemon=True,
    )
    t.start()
    return {"status": "started", "mode": "file", "target": filepath}, 200


def handle_transpile_directory(body: dict, handler) -> tuple[dict, int]:
    directory = body.get("directory", "")
    if not directory or not os.path.isdir(directory):
        return {"error": f"Invalid directory: {directory}"}, 400

    if _transpile_status.get("running"):
        return {"error": "Transpilation already in progress"}, 409

    cfg = body.get("config", {})
    t = threading.Thread(
        target=_run_transpile,
        args=("directory", str(Path(directory).resolve()), cfg),
        daemon=True,
    )
    t.start()
    return {"status": "started", "mode": "directory", "target": directory}, 200


def handle_transpile_pipeline(body: dict, handler) -> tuple[dict, int]:
    directory = body.get("directory", "")
    if not directory or not os.path.isdir(directory):
        return {"error": f"Invalid directory: {directory}"}, 400

    if _transpile_status.get("running"):
        return {"error": "Transpilation already in progress"}, 409

    cfg = body.get("config", {})
    t = threading.Thread(
        target=_run_transpile,
        args=("pipeline", str(Path(directory).resolve()), cfg),
        daemon=True,
    )
    t.start()
    return {"status": "started", "mode": "pipeline", "target": directory}, 200


def handle_transpile_status(params: dict, handler) -> tuple[dict, int]:
    return _status_snapshot(), 200


# ── Route tables ─────────────────────────────────────────────────────────

POST_ROUTES = {
    "/api/transpile-file": handle_transpile_file,
    "/api/transpile-directory": handle_transpile_directory,
    "/api/transpile-pipeline": handle_transpile_pipeline,
}

GET_ROUTES = {
    "/api/transpile-status": handle_transpile_status,
}
