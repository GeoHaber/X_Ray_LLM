"""
PM Dashboard + CGC API routes.
"""

import os
import threading
from pathlib import Path

from services.app_state import state
from services.scan_manager import execute_monkey_tests, execute_wire_test


def _dir_from_body(body: dict) -> tuple[str | None, dict | None]:
    directory = body.get("directory", "")
    if not directory or not os.path.isdir(directory):
        return None, {"error": f"Invalid directory: {directory}"}
    return str(Path(directory).resolve()), None


def handle_risk_heatmap(body, handler):
    from analyzers import compute_risk_heatmap

    d, err = _dir_from_body(body)
    if err:
        return err, 400
    return compute_risk_heatmap(d, body.get("findings")), 200


def handle_module_cards(body, handler):
    from analyzers import compute_module_cards

    d, err = _dir_from_body(body)
    if err:
        return err, 400
    return compute_module_cards(d, body.get("findings")), 200


def handle_confidence(body, handler):
    from analyzers import compute_confidence_meter

    d, err = _dir_from_body(body)
    if err:
        return err, 400
    return compute_confidence_meter(d, body.get("findings")), 200


def handle_sprint_batches(body, handler):
    from analyzers import compute_sprint_batches

    return compute_sprint_batches(body.get("findings"), body.get("smells")), 200


def handle_architecture(body, handler):
    from analyzers import compute_architecture_map

    d, err = _dir_from_body(body)
    if err:
        return err, 400
    return compute_architecture_map(d), 200


def handle_call_graph(body, handler):
    from analyzers import compute_call_graph

    d, err = _dir_from_body(body)
    if err:
        return err, 400
    return compute_call_graph(d), 200


def handle_impact_graph(body, handler):
    from analyzers import compute_impact_graph

    d, err = _dir_from_body(body)
    if err:
        return err, 400
    return compute_impact_graph(d, body.get("findings")), 200


def handle_chat(body, handler):
    from services.chat_engine import chat_reply

    message = body.get("message", "").strip()
    if not message:
        return {"reply": "Please type a message."}, 200
    return {"reply": chat_reply(message, body)}, 200


def handle_project_review(body, handler):
    from analyzers import compute_project_review

    d, err = _dir_from_body(body)
    if err:
        return err, 400
    return compute_project_review(
        d,
        findings=body.get("findings"),
        summary=body.get("summary"),
        files_scanned=body.get("files_scanned", 0),
        smells=body.get("smells"),
        dead_functions=body.get("dead_functions"),
        health=body.get("health"),
        satd=body.get("satd"),
        duplicates=body.get("duplicates"),
    ), 200


def handle_circular_calls(body, handler):
    from analyzers import detect_circular_calls

    d, err = _dir_from_body(body)
    if err:
        return err, 400
    return detect_circular_calls(d), 200


def handle_coupling(body, handler):
    from analyzers import compute_coupling_metrics

    d, err = _dir_from_body(body)
    if err:
        return err, 400
    return compute_coupling_metrics(d), 200


def handle_unused_imports(body, handler):
    from analyzers import detect_unused_imports

    d, err = _dir_from_body(body)
    if err:
        return err, 400
    return detect_unused_imports(d), 200


def handle_monkey_test(body, handler):
    if state.monkey_test_thread and state.monkey_test_thread.is_alive():
        return {"status": "already_running"}, 200
    state.reset_monkey_test()
    host = handler.server.server_address[0]
    port = handler.server.server_address[1]
    base_url = f"http://{host}:{port}"
    t = threading.Thread(target=execute_monkey_tests, args=(base_url,), daemon=True)
    t.start()
    state.monkey_test_thread = t
    return {"status": "started"}, 200


def handle_wire_test(body, handler):
    d, err = _dir_from_body(body)
    if err:
        return err, 400
    state.reset_wire_test()
    host = handler.server.server_address[0]
    port = handler.server.server_address[1]
    base_url = f"http://{host}:{port}"
    t = threading.Thread(
        target=execute_wire_test,
        args=(d, base_url),
        daemon=True,
    )
    t.start()
    state.wire_test_thread = t
    return {"status": "started"}, 200


def handle_wire_progress(params, handler):
    if state.wire_test_progress is not None:
        return state.wire_test_progress, 200
    if state.wire_test_results is not None:
        return {"status": "done", "results": state.wire_test_results}, 200
    return {"status": "idle"}, 200


def handle_monkey_progress(params, handler):
    if state.monkey_test_progress is not None and state.monkey_test_progress.get("status") == "running":
        return state.monkey_test_progress, 200
    if state.monkey_test_results is not None:
        return state.monkey_test_results, 200
    return {"status": "idle"}, 200


GET_ROUTES = {
    "/api/wire-progress": handle_wire_progress,
    "/api/monkey-progress": handle_monkey_progress,
}

POST_ROUTES = {
    "/api/risk-heatmap": handle_risk_heatmap,
    "/api/module-cards": handle_module_cards,
    "/api/confidence": handle_confidence,
    "/api/sprint-batches": handle_sprint_batches,
    "/api/architecture": handle_architecture,
    "/api/call-graph": handle_call_graph,
    "/api/impact-graph": handle_impact_graph,
    "/api/chat": handle_chat,
    "/api/project-review": handle_project_review,
    "/api/circular-calls": handle_circular_calls,
    "/api/coupling": handle_coupling,
    "/api/unused-imports": handle_unused_imports,
    "/api/monkey-test": handle_monkey_test,
    "/api/wire-test": handle_wire_test,
}
