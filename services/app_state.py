"""
Thread-safe application state singleton.

All mutable server-wide state lives here behind a lock so route handlers
and background threads can access it safely.
"""

import os
import threading


class AppState:
    """Holds all mutable server state with thread-safe access."""

    _instance: "AppState | None" = None
    _init_lock = threading.Lock()

    def __new__(cls) -> "AppState":
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._lock = threading.RLock()

        # Scan state
        self.scan_progress: dict | None = None
        self.last_scan_result: dict | None = None
        self.scan_thread: threading.Thread | None = None

        # Wire test state
        self.wire_test_results: dict | None = None
        self.wire_test_progress: dict | None = None
        self.wire_test_thread: threading.Thread | None = None

        # Monkey test state
        self.monkey_test_results: dict | None = None
        self.monkey_test_progress: dict | None = None
        self.monkey_test_thread: threading.Thread | None = None

        # Abort signal
        self.abort = threading.Event()

        # Rust subprocess tracking
        self.rust_proc = None
        self.rust_proc_lock = threading.Lock()

        # Debug mode
        self.debug = os.environ.get("XRAY_DEBUG", "").lower() in (
            "1",
            "true",
            "yes",
        )

        self._initialized = True

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    # ── Convenience helpers ──────────────────────────────────────────

    def reset_scan(self):
        with self._lock:
            self.last_scan_result = None
            self.scan_progress = None

    def set_scan_progress(self, progress: dict):
        with self._lock:
            self.scan_progress = progress

    def set_scan_result(self, result: dict):
        with self._lock:
            self.last_scan_result = result

    def reset_wire_test(self):
        with self._lock:
            self.wire_test_results = None
            self.wire_test_progress = {"status": "starting", "step": 0, "total": 0}

    def reset_monkey_test(self):
        with self._lock:
            self.monkey_test_results = None
            self.monkey_test_progress = {"status": "starting", "passed": 0, "failed": 0}


# Module-level singleton for easy import
state = AppState()
