"""
Library extraction fixture — file A.
Functions with the same names appear across multiple files,
triggering the LibraryAdvisor's cross-file name analysis.
"""


def validate_email(email: str) -> bool:
    """Check if email format is valid."""
    import re
    pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
    return bool(re.match(pattern, email))


def format_currency(amount: float, currency: str = "USD") -> str:
    """Format a monetary amount."""
    symbols = {"USD": "$", "EUR": "€", "GBP": "£"}
    sym = symbols.get(currency, currency)
    return f"{sym}{amount:,.2f}"


def retry_operation(func, max_retries=3, delay=1.0):
    """Retry a function call up to max_retries times."""
    import time
    for attempt in range(max_retries):
        try:
            return func()
        except Exception:
            if attempt == max_retries - 1:
                raise
            time.sleep(delay)
