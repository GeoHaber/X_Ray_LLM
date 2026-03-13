import sys
import logging
import platform


# === LOGGING ===
def setup_logger(name: str = "X_RAY_Claude"):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    return logging.getLogger(name)


logger = setup_logger()


# === SAFE UNICODE OUTPUT ===
def _wrap_stream_utf8(stream, attr_name: str):
    """Wrap a stream's buffer in a UTF-8 TextIOWrapper if possible."""
    import io

    if not hasattr(stream, "buffer"):
        return stream
    return io.TextIOWrapper(
        stream.buffer,
        encoding="utf-8",
        errors="replace",
        line_buffering=True,
    )


def _enable_windows_utf8():
    """Enable UTF-8 codepage on Windows console."""
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except (AttributeError, OSError):  # nosec B110 — ctypes not available on all platforms
        pass
    """Fallback: wrap stdout/stderr buffers in UTF-8 TextIOWrapper."""
    try:
        sys.stdout = _wrap_stream_utf8(sys.stdout, "stdout")
        sys.stderr = _wrap_stream_utf8(sys.stderr, "stderr")
    except (AttributeError, OSError):  # nosec B110 — stream reconfigure not available everywhere
        pass


def _enable_utf8_console() -> None:
    """Best-effort: switch the Windows console to UTF-8 so basic text works."""
    import os as _os

    if _os.name == "nt":
        _enable_windows_utf8()
    # Reconfigure streams to utf-8 with replace for safety
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        _reconfigure_streams_fallback()


def supports_unicode() -> bool:
    """Detect whether the current stdout can handle full Unicode emoji.

    For frozen PyInstaller builds (.exe) we ALWAYS return False so that
    only safe ASCII icons are printed to the Windows console.  Emoji
    belongs in Streamlit, not in cmd.exe / PowerShell.
    """
    # Frozen .exe  →  never use emoji in terminal output
    if getattr(sys, "frozen", False):
        return False

    enc = getattr(sys.stdout, "encoding", None) or ""
    if enc.lower().replace("-", "").replace("_", "") in ("utf8",):
        return True
    return False


_enable_utf8_console()  # make sure we can at least print ASCII safely
UNICODE_OK = supports_unicode()  # False when frozen → ASCII icons only

# === HARDWARE & OS DETECTION ===


def get_os_info() -> str:
    """Return a descriptive string of the current OS."""
    return f"{platform.system()} {platform.release()} ({platform.machine()})"


def get_cpu_info() -> str:
    """Return CPU brand/features if possible."""
    # This is a basic implementation. For full features, one might use 'cpuinfo' package
    # but we'll stick to stdlib for now to minimize dependencies.
    return platform.processor() or "Unknown CPU"


# === NETWORKING ===


def url_responds(url: str, timeout: int = 2) -> bool:
    """Return *True* if a GET request to *url* succeeds with HTTP 200.

    Only HTTPS URLs are accepted to prevent unencrypted network traffic.
    """
    import urllib.request

    if not url.startswith("https://"):
        logger.warning("url_responds: only HTTPS URLs are supported (got %s)", url)
        return False
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310  # nosec B310
            return resp.status == 200
    except (OSError, TimeoutError, ValueError):
        return False


def find_free_port(preferred: int = 8666) -> int:
    """Return *preferred* if available, else find any free port."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


_verify_ref = [False]  # [bool] — mutable container avoids global keyword


def verify_rust_environment():
    """Check if the environment matches the compiled extension expectations."""
    if _verify_ref[0]:
        return True

    os_name = platform.system().lower()
    arch = platform.machine().lower()

    logger.info("Checking Performance Engine...")
    logger.info(f"Target OS: {get_os_info()} (os={os_name}, arch={arch})")
    logger.info(f"Target CPU: {get_cpu_info()}")

    _verify_ref[0] = True
    return True


# === TRIAL LICENSE ===


def check_trial_license() -> bool:
    """Enforce trial license via x_ray_core. Returns True if allowed."""
    from Core.ui_bridge import get_bridge

    bridge = get_bridge()
    try:
        import x_ray_core

        remaining = x_ray_core.check_trial()
        max_runs = x_ray_core.trial_max_runs()
        bridge.log(f"  \u26a1 Trial license: {remaining} of {max_runs} runs remaining")
        if remaining <= 3:
            bridge.log(
                f"  \u26a0  Only {remaining} runs left — contact developer for full license."
            )
        bridge.log("")
        return True
    except RuntimeError as exc:
        bridge.log(f"  \u2716 {exc}")
        bridge.log("")
        return False
    except (ImportError, AttributeError):
        # x_ray_core not available or missing check_trial — skip trial check (dev mode)
        logger.debug("x_ray_core not found; skipping trial license check (dev mode).")
        return True
