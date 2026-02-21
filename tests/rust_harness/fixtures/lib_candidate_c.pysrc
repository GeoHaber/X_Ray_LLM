"""
Library extraction fixture — file C.
Third appearance of the same function names.
"""


def validate_email(email_str: str) -> bool:
    """Return True if email_str looks like a valid email."""
    parts = email_str.split("@")
    if len(parts) != 2:
        return False
    user_part, domain_part = parts
    return bool(user_part) and "." in domain_part


def format_currency(amount: float, currency: str = "USD") -> str:
    """Pretty-print a currency amount."""
    prefix_map = {"USD": "$", "EUR": "€", "GBP": "£"}
    prefix = prefix_map.get(currency, f"{currency} ")
    return f"{prefix}{amount:,.2f}"
