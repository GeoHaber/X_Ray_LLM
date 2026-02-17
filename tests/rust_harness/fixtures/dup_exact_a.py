"""
Exact duplicate fixture — file A.
Contains functions that are byte-for-byte identical to those in dup_exact_b.py.
"""


def compute_checksum(data: bytes) -> str:
    """Compute a hex checksum of the given bytes."""
    import hashlib
    h = hashlib.sha256(data)
    digest = h.hexdigest()
    return digest


def format_timestamp(epoch: float) -> str:
    """Format a Unix epoch into ISO-8601."""
    from datetime import datetime, timezone
    dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
    return dt.isoformat()


def clamp(value: float, lo: float, hi: float) -> float:
    """Clamp a value between lo and hi."""
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value
