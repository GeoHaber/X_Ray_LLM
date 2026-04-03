"""
Incremental Watch Mode — Watches for file changes and triggers re-scans.
Supports WebSocket-style push via callback functions.
"""

from __future__ import annotations

import os
import time
import hashlib
import threading
import logging
from pathlib import Path
from dataclasses import dataclass, field

log = logging.getLogger("xray.watcher")

_SKIP_DIRS = frozenset({
    "__pycache__", ".git", "node_modules", ".venv", "venv", ".tox",
    ".mypy_cache", ".pytest_cache", "dist", "build", "rust_output",
    "site-packages", ".eggs",
})

_WATCH_EXTS = frozenset({
    ".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".htm", ".vue", ".svelte", ".rs",
})


@dataclass
class FileState:
    path: str
    mtime: float
    hash: str
    size: int


@dataclass
class WatchEvent:
    event_type: str   # "created" | "modified" | "deleted"
    file_path: str
    relative_path: str
    timestamp: float


@dataclass
class WatcherState:
    running: bool = False
    directory: str = ""
    file_states: dict[str, FileState] = field(default_factory=dict)
    events: list[WatchEvent] = field(default_factory=list)
    scan_count: int = 0
    last_scan_time: float = 0.0
    error: str | None = None


class FileWatcher:
    """
    Watches a directory for changes to source files and triggers callbacks.

    Usage:
        watcher = FileWatcher("/path/to/project")
        watcher.on_change = lambda events: print(f"{len(events)} files changed")
        watcher.on_scan_complete = lambda results: print(f"Scan done: {len(results)} findings")
        watcher.start()
        # ... later
        watcher.stop()
    """

    def __init__(self, directory: str, poll_interval: float = 2.0,
                 debounce: float = 1.0):
        self.directory = str(Path(directory).resolve())
        self.poll_interval = poll_interval
        self.debounce = debounce
        self.state = WatcherState(directory=self.directory)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Callbacks
        self.on_change: callable | None = None       # (events: list[WatchEvent]) -> None
        self.on_scan_complete: callable | None = None  # (results: dict) -> None
        self.on_error: callable | None = None          # (error: str) -> None

    def start(self):
        """Start watching in a background thread."""
        if self.state.running:
            return
        self.state.running = True
        self._stop_event.clear()
        self._build_initial_state()
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()
        log.info("Watcher started for %s", self.directory)

    def stop(self):
        """Stop the watcher."""
        self.state.running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        log.info("Watcher stopped")

    def get_state(self) -> dict:
        """Get current watcher state."""
        return {
            "running": self.state.running,
            "directory": self.state.directory,
            "watched_files": len(self.state.file_states),
            "scan_count": self.state.scan_count,
            "last_scan_time": self.state.last_scan_time,
            "pending_events": len(self.state.events),
            "error": self.state.error,
        }

    def _build_initial_state(self):
        """Snapshot current file states."""
        self.state.file_states.clear()
        for fp in self._walk_files():
            try:
                stat = os.stat(fp)
                self.state.file_states[fp] = FileState(
                    path=fp,
                    mtime=stat.st_mtime,
                    hash=self._quick_hash(fp),
                    size=stat.st_size,
                )
            except OSError:
                continue

    def _walk_files(self) -> list[str]:
        """Get all watchable files."""
        files = []
        for dirpath, dirnames, filenames in os.walk(self.directory):
            parts = Path(dirpath).parts
            if any(p in _SKIP_DIRS or p.startswith((".venv", "venv"))
                   for p in parts):
                dirnames.clear()
                continue
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS
                           and not d.startswith((".venv", "venv", "__pycache__"))]
            for fn in filenames:
                ext = os.path.splitext(fn)[1].lower()
                if ext in _WATCH_EXTS:
                    files.append(os.path.join(dirpath, fn))
        return files

    def _quick_hash(self, fp: str) -> str:
        """Quick content hash for change detection."""
        try:
            with open(fp, "rb") as f:
                return hashlib.md5(f.read(64 * 1024)).hexdigest()  # First 64KB
        except OSError:
            return ""

    def _watch_loop(self):
        """Main polling loop."""
        pending_changes: list[WatchEvent] = []
        last_change_time = 0.0

        while not self._stop_event.is_set():
            try:
                events = self._detect_changes()
                if events:
                    pending_changes.extend(events)
                    last_change_time = time.time()
                    self.state.events.extend(events)

                # Debounce: trigger scan after debounce period of no changes
                if pending_changes and (time.time() - last_change_time) >= self.debounce:
                    self._trigger_scan(pending_changes)
                    pending_changes.clear()

            except Exception as exc:
                self.state.error = str(exc)
                if self.on_error:
                    self.on_error(str(exc))
                log.error("Watcher error: %s", exc)

            self._stop_event.wait(self.poll_interval)

    def _detect_changes(self) -> list[WatchEvent]:
        """Detect file changes since last check."""
        events = []
        now = time.time()
        current_files = set(self._walk_files())
        known_files = set(self.state.file_states.keys())

        # New files
        for fp in current_files - known_files:
            try:
                stat = os.stat(fp)
                self.state.file_states[fp] = FileState(
                    path=fp, mtime=stat.st_mtime,
                    hash=self._quick_hash(fp), size=stat.st_size,
                )
                events.append(WatchEvent(
                    event_type="created",
                    file_path=fp,
                    relative_path=os.path.relpath(fp, self.directory),
                    timestamp=now,
                ))
            except OSError:
                continue

        # Deleted files
        for fp in known_files - current_files:
            del self.state.file_states[fp]
            events.append(WatchEvent(
                event_type="deleted",
                file_path=fp,
                relative_path=os.path.relpath(fp, self.directory),
                timestamp=now,
            ))

        # Modified files
        for fp in current_files & known_files:
            try:
                stat = os.stat(fp)
                old = self.state.file_states[fp]
                if stat.st_mtime > old.mtime:
                    new_hash = self._quick_hash(fp)
                    if new_hash != old.hash:
                        self.state.file_states[fp] = FileState(
                            path=fp, mtime=stat.st_mtime,
                            hash=new_hash, size=stat.st_size,
                        )
                        events.append(WatchEvent(
                            event_type="modified",
                            file_path=fp,
                            relative_path=os.path.relpath(fp, self.directory),
                            timestamp=now,
                        ))
            except OSError:
                continue

        return events

    def _trigger_scan(self, events: list[WatchEvent]):
        """Trigger incremental scan for changed files."""
        changed_files = [e.file_path for e in events if e.event_type != "deleted"]
        if not changed_files:
            return

        log.info("Watcher: %d files changed, triggering scan", len(changed_files))

        if self.on_change:
            self.on_change([{
                "type": e.event_type,
                "file": e.relative_path,
                "timestamp": e.timestamp,
            } for e in events])

        # Run scan on changed files only
        try:
            from xray.scanner import scan_file, ALL_RULES
            findings = []
            for fp in changed_files:
                results = scan_file(fp, ALL_RULES)
                findings.extend(results)

            self.state.scan_count += 1
            self.state.last_scan_time = time.time()

            result = {
                "scan_number": self.state.scan_count,
                "files_scanned": len(changed_files),
                "findings": len(findings),
                "changed_files": [os.path.relpath(f, self.directory) for f in changed_files],
                "timestamp": time.time(),
            }

            if self.on_scan_complete:
                self.on_scan_complete(result)

        except Exception as exc:
            log.error("Incremental scan failed: %s", exc)
            if self.on_error:
                self.on_error(f"Scan failed: {exc}")


# ── Module-level singleton for API use ────────────────────────────────

_active_watcher: FileWatcher | None = None
_watcher_events: list[dict] = []
_watcher_scan_results: list[dict] = []


def start_watcher(directory: str, poll_interval: float = 2.0) -> dict:
    """Start the file watcher (called from API)."""
    global _active_watcher, _watcher_events, _watcher_scan_results

    if _active_watcher and _active_watcher.state.running:
        _active_watcher.stop()

    _watcher_events.clear()
    _watcher_scan_results.clear()

    _active_watcher = FileWatcher(directory, poll_interval=poll_interval)
    _active_watcher.on_change = lambda evts: _watcher_events.extend(evts)
    _active_watcher.on_scan_complete = lambda res: _watcher_scan_results.append(res)
    _active_watcher.start()

    return {"status": "started", "directory": directory}


def stop_watcher() -> dict:
    """Stop the file watcher."""
    global _active_watcher
    if _active_watcher:
        _active_watcher.stop()
        state = _active_watcher.get_state()
        _active_watcher = None
        return {"status": "stopped", **state}
    return {"status": "not_running"}


def get_watcher_status() -> dict:
    """Get current watcher status and recent events."""
    if _active_watcher:
        return {
            **_active_watcher.get_state(),
            "recent_events": _watcher_events[-50:],
            "recent_scans": _watcher_scan_results[-10:],
        }
    return {"running": False, "recent_events": [], "recent_scans": []}
