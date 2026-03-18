import re
import threading
import time
from pathlib import Path

import requests


class WireConnector:
    """
    Wire Connector Engine — Performs automated stress and connectivity tests
    between the UI and the API endpoints.
    """

    def __init__(self, base_url="http://127.0.0.1:8077"):
        self.base_url = base_url
        self.results = []
        self.running = False
        self._stop_event = threading.Event()
        self.root_dir = Path(__file__).parent.parent

    def discover_wires(self):
        """Parse ui.html and ui_server.py to find all API connections."""
        ui_html = self.root_dir / "ui.html"
        ui_server = self.root_dir / "ui_server.py"

        endpoints = set()

        # 1. Parse ui.html for api() calls
        if ui_html.exists():
            content = ui_html.read_text(encoding="utf-8", errors="ignore")
            # matches api('/api/something') or api("/api/something")
            matches = re.findall(r"api\(['\"](/api/[a-zA-Z0-9\-_]+)['\"]", content)
            for m in matches:
                endpoints.add(("POST" if "method: 'POST'" in content[content.find(m):content.find(m)+200] else "GET", m))

        # 2. Parse ui_server.py for endpoint handlers
        if ui_server.exists():
            content = ui_server.read_text(encoding="utf-8", errors="ignore")
            matches = re.findall(r"path == ['\"](/api/[a-zA-Z0-9\-_]+)['\"]", content)
            for m in matches:
                # Default to POST for most endpoints in this app unless known otherwise
                method = "GET" if m in ["/api/info", "/api/browse", "/api/scan-progress", "/api/scan-result", "/api/wire-progress"] else "POST"
                endpoints.add((method, m))

        # Sort for consistency
        return sorted(list(endpoints))

    def run_tests(self, directory, progress_callback=None):
        self.running = True
        self._stop_event.clear()
        self.results = []

        found_wires = self.discover_wires()
        total = len(found_wires)

        # Default payloads for testing
        default_payloads = {
            "/api/scan": {"directory": directory, "engine": "python", "severity": "LOW"},
            "/api/chat": {"message": "Hello"},
            "/api/remediation-time": {"findings": []},
            "/api/apply-fixes-bulk": {"findings": []},
            "/api/preview-fix": {"finding": {}},
            "/api/apply-fix": {"finding": {}},
            "/api/wire-test": {"directory": directory}, # recursion check prevented below
        }

        for i, (method, endpoint) in enumerate(found_wires):
            if self._stop_event.is_set():
                break

            # Skip self-recursion or endpoints that might be destructive or loop-heavy
            if endpoint in ["/api/wire-test", "/api/wire-progress", "/api/abort"]:
                continue

            payload = default_payloads.get(endpoint, {"directory": directory})
            # Special case for browse/scan-progress which are GET but might need params
            if endpoint == "/api/browse" and method == "GET":
                payload = {"path": directory}
            elif method == "GET":
                payload = None # Default GET params

            target_url = f"{self.base_url}{endpoint}"
            start_time = time.perf_counter()

            if progress_callback:
                progress_callback({
                    "step": i + 1,
                    "total": total,
                    "endpoint": endpoint,
                    "status": "testing"
                })

            try:
                if method == "GET":
                    resp = requests.get(target_url, params=payload, timeout=10)
                else:
                    resp = requests.post(target_url, json=payload, timeout=10)

                duration = round((time.perf_counter() - start_time) * 1000, 2)
                # Count as "wired" if the server responded (connection works),
                # but track the actual status so 404/400 can be flagged separately.
                connected = resp.status_code != 0
                success = 200 <= resp.status_code < 500  # server responded
                # We want to know if the "wire" works, i.e., the server responds.
                # 4xx means wired but possibly wrong payload; 5xx is a server bug.

                result = {
                    "method": method,
                    "endpoint": endpoint,
                    "status_code": resp.status_code,
                    "duration_ms": duration,
                    "success": success,
                    "error": None if success else resp.text[:200]
                }
            except Exception as e:
                duration = round((time.perf_counter() - start_time) * 1000, 2)
                result = {
                    "method": method,
                    "endpoint": endpoint,
                    "status_code": 0,
                    "duration_ms": duration,
                    "success": False,
                    "error": str(e)
                }

            self.results.append(result)

            if progress_callback:
                progress_callback({
                    "step": i + 1,
                    "total": total,
                    "endpoint": endpoint,
                    "status": "testing", # status is still testing until we finish all
                    "result": result
                })

            time.sleep(0.05)

        self.running = False
        return self.results

    def stop(self):
        self._stop_event.set()
        self.running = False

def start_wire_test(directory, base_url, callback):
    """Entry point for ui_server to run the test in a thread."""
    wc = WireConnector(base_url)
    return wc.run_tests(directory, callback)
