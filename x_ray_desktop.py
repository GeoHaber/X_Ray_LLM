#!/usr/bin/env python3
"""
X-Ray Desktop App — Native Windows Window (pywebview + Streamlit)
==================================================================

Runs the full Streamlit UI inside a native desktop window using pywebview
with Edge WebView2.  Looks and feels like a native Windows application —
no browser chrome, no address bar, no tabs.

Architecture:
    1. Start Streamlit server in a background thread
    2. Wait for the server to become ready (poll)
    3. Open a pywebview window pointing at http://localhost:{port}
    4. When the window is closed → shut down the server + exit

Usage:
    x_ray_desktop.exe                  # native window on auto port
    python x_ray_desktop.py            # same, from source
"""

from __future__ import annotations

import os
import sys
import socket
import threading
import time
from pathlib import Path

from Core.utils import find_free_port

# ---------------------------------------------------------------------------
# PyInstaller frozen-app fixups
# ---------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    _BUNDLE_DIR = Path(sys._MEIPASS)
    _EXE_DIR = Path(sys.executable).parent

    if str(_BUNDLE_DIR) not in sys.path:
        sys.path.insert(0, str(_BUNDLE_DIR))

    os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    os.environ.setdefault("STREAMLIT_SERVER_HEADLESS", "true")
    os.environ.setdefault("STREAMLIT_SERVER_FILE_WATCHER_TYPE", "none")
    os.environ.setdefault("STREAMLIT_GLOBAL_DEVELOPMENT_MODE", "false")
    os.environ.setdefault("STREAMLIT_CLIENT_TOOLBAR_MODE", "viewer")

    # Suppress Streamlit first-run prompts
    st_config_dir = Path.home() / ".streamlit"
    st_config_dir.mkdir(exist_ok=True)
    config_file = st_config_dir / "config.toml"
    if not config_file.exists():
        config_file.write_text(
            "[browser]\n"
            "gatherUsageStats = false\n\n"
            "[server]\n"
            "headless = true\n"
            'fileWatcherType = "none"\n',
            encoding="utf-8",
        )
else:
    _BUNDLE_DIR = Path(__file__).resolve().parent
    _EXE_DIR = _BUNDLE_DIR

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _wait_for_server(port: int, timeout: float = 30.0) -> bool:
    """Block until localhost:port accepts a TCP connection (or timeout)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def _locate_ui_script() -> Path:
    """Find x_ray_ui.py — bundled in _MEIPASS or next to the exe."""
    for base in (_BUNDLE_DIR, _EXE_DIR, Path.cwd()):
        p = base / "x_ray_ui.py"
        if p.is_file():
            return p
    print("ERROR: Cannot find x_ray_ui.py")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Streamlit server (runs in background thread)
# ---------------------------------------------------------------------------


def _run_streamlit(port: int, ui_script: Path):
    """Start the Streamlit server (blocking — run in a thread).

    Patches signal.signal to no-op since we're running in a non-main thread
    and Streamlit tries to register SIGTERM/SIGINT handlers.
    """
    import signal

    _orig_signal = signal.signal

    def _safe_signal(signum, handler):
        try:
            return _orig_signal(signum, handler)
        except ValueError:
            # "signal only works in main thread" — ignore silently
            return signal.SIG_DFL

    signal.signal = _safe_signal

    os.environ["STREAMLIT_SERVER_PORT"] = str(port)
    os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"
    os.environ["STREAMLIT_SERVER_FILE_WATCHER_TYPE"] = "none"
    os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    os.environ["STREAMLIT_GLOBAL_DEVELOPMENT_MODE"] = "false"
    os.environ["STREAMLIT_CLIENT_TOOLBAR_MODE"] = "viewer"
    os.environ["STREAMLIT_SERVER_ENABLE_CORS"] = "false"
    os.environ["STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION"] = "false"

    from streamlit import config

    config.set_option("server.port", port)
    config.set_option("server.headless", True)
    config.set_option("server.fileWatcherType", "none")
    config.set_option("browser.gatherUsageStats", False)
    config.set_option("global.developmentMode", False)
    config.set_option("client.toolbarMode", "viewer")
    config.set_option("server.enableCORS", False)
    config.set_option("server.enableXsrfProtection", False)

    from streamlit.web.bootstrap import run as streamlit_run

    try:
        streamlit_run(
            main_script_path=str(ui_script),
            is_hello=False,
            args=[],
            flag_options={},
        )
    except SystemExit:
        pass  # Streamlit may call sys.exit on shutdown — that's fine
    except Exception as exc:
        if "signal" in str(exc).lower():
            pass  # Non-fatal — signal handler in non-main thread
        else:
            print(f"Streamlit error: {exc}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    port = find_free_port()
    ui_script = _locate_ui_script()
    url = f"http://localhost:{port}"

    print(r"""
 ___  __    ____   __   _  _
( \/ )(  _ \(  _ \ / _\ ( \/ )
 )  (  )   / )   //    \ )  /
(_/\_)(__\_)(__\_)\_/\_/(__/

  X-Ray Code Scanner — Desktop App
  ===================================
""")
    print(f"  Server:  {url}")
    print(f"  UI:      {ui_script}")

    # Start Streamlit in a daemon thread
    server_thread = threading.Thread(
        target=_run_streamlit, args=(port, ui_script), daemon=True
    )
    server_thread.start()

    # Wait for the server to be ready
    print("  Waiting for server ...", end="", flush=True)
    if not _wait_for_server(port, timeout=45.0):
        print(" TIMEOUT — server did not start.")
        sys.exit(1)
    print(" ready!")

    # Open native desktop window
    import webview

    webview.create_window(
        title="X-Ray Code Scanner",
        url=url,
        width=1400,
        height=920,
        min_size=(900, 600),
        resizable=True,
        text_select=True,
    )

    # webview.start() blocks until the window is closed
    webview.start(
        gui="edgechromium",  # Use Edge WebView2 (built-in on Win10/11)
        debug=False,
    )

    # Window closed — clean exit
    print("\n  Window closed — shutting down.")
    os._exit(0)  # Force-kill the Streamlit thread


if __name__ == "__main__":
    main()
