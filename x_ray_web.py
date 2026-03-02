#!/usr/bin/env python3
"""
X-Ray Standalone Web App Launcher
===================================

This is the PyInstaller entry point that starts the Streamlit-based
X-Ray web interface as a self-contained Windows application.

No Python or Streamlit installation required — everything is bundled.

Usage:
    x_ray_web.exe                        # opens browser on port 8666
    x_ray_web.exe --port 9000            # custom port
    x_ray_web.exe --no-browser           # don't auto-open browser
"""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser
import threading
import time
from pathlib import Path

from Core.utils import find_free_port

# ---------------------------------------------------------------------------
# PyInstaller frozen-app fixups
# ---------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    # _MEIPASS is the temp dir where PyInstaller extracts bundled files
    _BUNDLE_DIR = Path(sys._MEIPASS)
    _EXE_DIR = Path(sys.executable).parent

    # Ensure our project packages are importable
    if str(_BUNDLE_DIR) not in sys.path:
        sys.path.insert(0, str(_BUNDLE_DIR))

    # Streamlit looks for its static assets relative to its package location.
    # In a frozen app we need to make sure it can find them.
    os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    os.environ.setdefault("STREAMLIT_SERVER_HEADLESS", "true")
    os.environ.setdefault("STREAMLIT_SERVER_FILE_WATCHER_TYPE", "none")
    os.environ.setdefault("STREAMLIT_GLOBAL_DEVELOPMENT_MODE", "false")
    os.environ.setdefault("STREAMLIT_CLIENT_TOOLBAR_MODE", "viewer")

    # Create a minimal Streamlit config to suppress prompts
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


def _open_browser_delayed(url: str, delay: float = 2.5):
    """Open the default browser after a short delay (gives server time to start)."""
    time.sleep(delay)
    webbrowser.open(url)


def _print_banner(port: int):
    """Display startup banner."""
    print(r"""
 ___  __    ____   __   _  _
( \/ )(  _ \(  _ \ / _\ ( \/ )
 )  (  )   / )   //    \ )  /
(_/\_)(__\_)(__\_)\_/\_/(__/

  X-Ray Code Scanner — Standalone Web App
  =========================================
""")
    print(f"  Starting server on http://localhost:{port}")
    print("  Press Ctrl+C to stop.\n")


def main():
    parser = argparse.ArgumentParser(description="X-Ray Standalone Web App")
    parser.add_argument(
        "--port", type=int, default=8666, help="Server port (default: 8666)"
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="Don't auto-open browser"
    )
    args = parser.parse_args()

    port = find_free_port(args.port)
    _print_banner(port)

    # Locate the UI script
    # When frozen, x_ray_ui.py is bundled as data inside _MEIPASS
    ui_script = _BUNDLE_DIR / "x_ray_ui.py"
    if not ui_script.is_file():
        # Fallback: look next to the .exe
        ui_script = _EXE_DIR / "x_ray_ui.py"
    if not ui_script.is_file():
        print(
            f"  ERROR: Cannot find x_ray_ui.py (checked {_BUNDLE_DIR} and {_EXE_DIR})"
        )
        sys.exit(1)

    print(f"  UI script: {ui_script}")

    # Auto-open browser
    if not args.no_browser:
        url = f"http://localhost:{port}"
        t = threading.Thread(target=_open_browser_delayed, args=(url, 3.0), daemon=True)
        t.start()

    # Launch Streamlit programmatically
    # Set config via environment variables (most reliable method)
    os.environ["STREAMLIT_SERVER_PORT"] = str(port)
    os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"
    os.environ["STREAMLIT_SERVER_FILE_WATCHER_TYPE"] = "none"
    os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    os.environ["STREAMLIT_GLOBAL_DEVELOPMENT_MODE"] = "false"
    os.environ["STREAMLIT_CLIENT_TOOLBAR_MODE"] = "viewer"

    from streamlit import config

    config.set_option("server.port", port)
    config.set_option("server.headless", True)
    config.set_option("server.fileWatcherType", "none")
    config.set_option("browser.gatherUsageStats", False)
    config.set_option("global.developmentMode", False)
    config.set_option("client.toolbarMode", "viewer")

    from streamlit.web.bootstrap import run as streamlit_run

    try:
        streamlit_run(
            main_script_path=str(ui_script),
            is_hello=False,
            args=[],
            flag_options={},
        )
    except KeyboardInterrupt:
        print("\n  X-Ray server stopped.")
    except Exception as e:
        print(f"\n  ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
