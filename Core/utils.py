
import sys
import logging
from pathlib import Path
from typing import List, Set

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
