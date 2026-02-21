"""
Library extraction fixture — file B.
Same function names as lib_candidate_a.py, reimplemented differently.
"""


def validate_email(address: str) -> bool:
    """Validate an email address."""
    if "@" not in address:
        return False
    local, domain = address.rsplit("@", 1)
    if not local or not domain:
        return False
    if "." not in domain:
        return False
    return True


def format_currency(value: float, currency: str = "USD") -> str:
    """Format a dollar amount."""
    symbols = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}
    sym = symbols.get(currency, currency)
    return f"{sym}{value:,.2f}"


def retry_operation(callable_fn, max_retries=3, delay=1.0):
    """Retry a callable up to max_retries times with delay."""
    import time
    last_error = None
    for i in range(max_retries):
        try:
            return callable_fn()
        except Exception as exc:
            last_error = exc
            time.sleep(delay)
    raise last_error
