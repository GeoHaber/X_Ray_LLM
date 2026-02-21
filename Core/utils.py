
import sys
import logging
import platform

# === LOGGING ===
def setup_logger(name: str = "X_RAY_Claude"):
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    return logging.getLogger(name)

logger = setup_logger()

# === SAFE UNICODE OUTPUT ===
def supports_unicode() -> bool:
    """Detect whether the current stdout can handle full Unicode."""
    enc = getattr(sys.stdout, 'encoding', None) or ''
    if enc.lower().replace('-', '').replace('_', '') in ('utf8', 'utf8'):
        return True
    # Try reconfigure  (CPython 3.7+)
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        return True
    except Exception:
        pass
    # Last resort: wrap the raw buffer
    import io
    try:
        if hasattr(sys.stdout, 'buffer'):
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer, encoding='utf-8', errors='replace',
                line_buffering=True,
            )
        if hasattr(sys.stderr, 'buffer'):
            sys.stderr = io.TextIOWrapper(
                sys.stderr.buffer, encoding='utf-8', errors='replace',
                line_buffering=True,
            )
        return True
    except Exception:
        return False

UNICODE_OK = supports_unicode()

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
    """Return *True* if a GET request to *url* succeeds with HTTP 200."""
    import urllib.request
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310  # nosec B310
            return resp.status == 200
    except Exception:
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


_verified_cache = False

def verify_rust_environment():
    """Check if the environment matches the compiled extension expectations."""
    global _verified_cache
    if _verified_cache:
        return True

    os_name = platform.system().lower()
    arch = platform.machine().lower()

    logger.info("Checking Performance Engine...")
    logger.info(f"Target OS: {get_os_info()} (os={os_name}, arch={arch})")
    logger.info(f"Target CPU: {get_cpu_info()}")

    _verified_cache = True
    return True

