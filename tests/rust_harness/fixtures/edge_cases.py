"""
Edge cases fixture — tests tricky AST / parsing scenarios:
  - async functions
  - decorated functions
  - nested functions (should NOT be extracted)
  - class inheritance
  - property decorators
  - star-args / kwargs
  - empty files (handled separately)
  - single-expression functions
"""
import functools


async def fetch_data(url: str) -> dict:
    """Async function that fetches data."""
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.json()


@functools.lru_cache(maxsize=256)
def cached_factorial(n: int) -> int:
    """Compute factorial with memoization."""
    if n <= 1:
        return 1
    return n * cached_factorial(n - 1)


def outer_function(data):
    """Has a nested function that should NOT be extracted."""
    def _inner_helper(item):
        return item * 2

    return [_inner_helper(d) for d in data]


class Animal:
    """Base class for animals."""

    def __init__(self, name: str, legs: int):
        """Initialize an animal."""
        self.name = name
        self.legs = legs

    def speak(self) -> str:
        """Override in subclass."""
        raise NotImplementedError


class Dog(Animal):
    """A dog (inherits Animal)."""

    def speak(self) -> str:
        """Dogs bark."""
        return f"{self.name} says Woof!"

    @property
    def description(self) -> str:
        """Formatted description."""
        return f"{self.name} ({self.legs} legs)"


def star_args_func(*args, **kwargs):
    """Function accepting *args and **kwargs."""
    total = sum(args)
    for key, val in kwargs.items():
        total += val
    return total


def single_line_func():
    return 42
