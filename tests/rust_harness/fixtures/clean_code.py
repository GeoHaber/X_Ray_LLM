"""
Clean code fixture — should produce ZERO smells.
Every function is small, documented, well-named, and low-complexity.
"""


def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


def greet(name: str) -> str:
    """Return a greeting message."""
    return f"Hello, {name}!"


def is_even(n: int) -> bool:
    """Check whether a number is even."""
    return n % 2 == 0


def has_items(collection: list) -> bool:
    """Return True if collection is non-empty."""
    return len(collection) > 0


class Point:
    """2D point with basic operations."""

    def __init__(self, x: float, y: float):
        """Initialize point."""
        self.x = x
        self.y = y

    def distance_to(self, other: "Point") -> float:
        """Euclidean distance to another point."""
        return ((self.x - other.x) ** 2 + (self.y - other.y) ** 2) ** 0.5

    def __repr__(self) -> str:
        return f"Point({self.x}, {self.y})"
