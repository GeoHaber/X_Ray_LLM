"""
Smell factory — every function/class here triggers a specific code smell.
Used to verify the Rust analyzer detects exactly the same set of issues.
"""


# ── 1. Long function (WARNING: 65 lines) ────────────────────────────────────
def long_function(data):
    x = 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    x += 1
    return x


# ── 2. Very long function (CRITICAL: 125 lines) ─────────────────────────────
def very_long_function(data):
    y = 0
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    y += 1
    return y


# ── 3. Deep nesting (WARNING: depth 4) ──────────────────────────────────────
def deeply_nested(data):
    """Process data with deep nesting."""
    for item in data:
        if item > 0:
            for sub in range(item):
                if sub % 2 == 0:
                    while sub > 0:
                        sub -= 1
    return data


# ── 4. Very deep nesting (CRITICAL: depth 6+) ───────────────────────────────
def very_deeply_nested(data):
    """Extremely nested logic."""
    for item in data:
        if item > 0:
            for sub in range(item):
                if sub % 2 == 0:
                    while sub > 0:
                        if sub > 5:
                            try:
                                sub -= 1
                            except Exception:
                                pass
    return data


# ── 5. High complexity (WARNING: complexity >= 10) ──────────────────────────
def high_complexity_func(a, b, c, d):
    """Many branches and conditions."""
    if a > 0:
        pass
    if b > 0:
        pass
    if c > 0:
        pass
    if d > 0:
        pass
    for i in range(a):
        if i > b:
            pass
        elif i > c:
            pass
    while a > 0:
        a -= 1
    try:
        pass
    except ValueError:
        pass
    except TypeError:
        pass
    return a


# ── 6. Too many parameters (WARNING: >= 6) ──────────────────────────────────
def too_many_params(a, b, c, d, e, f, g):
    """Function accepting too many positional args."""
    return a + b + c + d + e + f + g


# ── 7. Missing docstring on non-trivial public function ─────────────────────
def missing_docstring_function(data, config, options):
    result = []
    for item in data:
        if config.get("filter"):
            if options.get("transform"):
                result.append(item)
            else:
                result.append(str(item))
        else:
            result.append(item)
    if not result:
        result = [None]
    for r in result:
        if r is not None:
            pass
    return result


# ── 8. Too many returns (WARNING: >= 5) ──────────────────────────────────────
def too_many_returns(x):
    """Function with excessive return points."""
    if x < 0:
        return -1
    if x == 0:
        return 0
    if x == 1:
        return 1
    if x == 2:
        return 2
    if x == 3:
        return 3
    return x


# ── 9. Boolean blindness — returns bool but name doesn't hint ────────────────
def process_status(value: int) -> bool:
    """Process a value and return status."""
    return value > 0


# ── 10. Too many branches (WARNING: >= 8 if statements) ──────────────────────
def too_many_branches_func(x):
    """Too many if-branches."""
    if x == 1:
        return "one"
    if x == 2:
        return "two"
    if x == 3:
        return "three"
    if x == 4:
        return "four"
    if x == 5:
        return "five"
    if x == 6:
        return "six"
    if x == 7:
        return "seven"
    if x == 8:
        return "eight"
    if x == 9:
        return "nine"
    return "other"


# ── 11. God class (CRITICAL: >= 15 methods) ──────────────────────────────────
class GodClass:
    """A class that does everything."""

    def __init__(self):
        self.data = []

    def m1(self): pass
    def m2(self): pass
    def m3(self): pass
    def m4(self): pass
    def m5(self): pass
    def m6(self): pass
    def m7(self): pass
    def m8(self): pass
    def m9(self): pass
    def m10(self): pass
    def m11(self): pass
    def m12(self): pass
    def m13(self): pass
    def m14(self): pass
    def m15(self): pass
    def m16(self): pass


# ── 12. Dataclass candidate (INFO: <= 3 methods, has __init__, no bases) ─────
class DataHolder:
    def __init__(self, name, age, email):
        self.name = name
        self.age = age
        self.email = email

    def to_dict(self):
        return {"name": self.name, "age": self.age, "email": self.email}


# ── 13. Missing class docstring (INFO: class > 30 lines, no docstring) ───────
class UndocumentedProcessor:
    def __init__(self, config):
        self.config = config
        self.results = []

    def process(self, data):
        for item in data:
            if self.config.get("filter"):
                self.results.append(item)

    def summarize(self):
        return {
            "total": len(self.results),
            "items": self.results,
        }

    def reset(self):
        self.results = []

    def validate(self, item):
        if item is None:
            return False
        if not isinstance(item, dict):
            return False
        return True

    def export(self):
        return list(self.results)

    def count(self):
        return len(self.results)
