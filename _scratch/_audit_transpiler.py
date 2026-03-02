"""Audit the transpiler for weak spots across many Python patterns."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from Analysis.transpiler import transpile_function_code

tests = {
    "try/except": 'def safe(x):\n    try:\n        return int(x)\n    except ValueError:\n        return -1',
    "augmented assign (+=)": 'def inc(x: int) -> int:\n    x += 1\n    return x',
    "while loop": 'def countdown(n: int):\n    while n > 0:\n        n -= 1',
    "with statement": 'def read_file(path: str) -> str:\n    with open(path) as f:\n        return f.read()',
    "class def": 'class Point:\n    def __init__(self, x: float, y: float):\n        self.x = x\n        self.y = y',
    "dict comp": 'def invert(d: dict) -> dict:\n    return {v: k for k, v in d.items()}',
    "multiple return paths": 'def divide(a: float, b: float) -> float:\n    if b == 0:\n        return 0.0\n    return a / b',
    "nested function": 'def outer(x: int) -> int:\n    def inner(y):\n        return y * 2\n    return inner(x)',
    "string .lstrip()": 'def clean(s: str) -> str:\n    return s.lstrip()',
    "string .rstrip()": 'def clean(s: str) -> str:\n    return s.rstrip()',
    "string .find()": 'def locate(s: str, t: str) -> int:\n    return s.find(t)',
    "string .index()": 'def locate(s: str, t: str) -> int:\n    return s.index(t)',
    "string .title()": 'def title(s: str) -> str:\n    return s.title()',
    "string .isdigit()": 'def check(s: str) -> bool:\n    return s.isdigit()',
    "string .format()": 'def fmt(name: str) -> str:\n    return "Hello {}".format(name)',
    "tuple return": 'def swap(a, b):\n    return (a, b)',
    "tuple unpack assign": 'def swap(a, b):\n    a, b = b, a\n    return (a, b)',
    "walrus operator": 'def check(items):\n    if (n := len(items)) > 10:\n        return n',
    "assert statement": 'def validate(x: int):\n    assert x > 0',
    "del statement": 'def rm(d: dict, key: str):\n    del d[key]',
    "global statement": 'def inc():\n    global x\n    x += 1',
    "starred unpack": 'def first_last(items):\n    first, *middle, last = items\n    return (first, last)',
    "match/case": 'def classify(x: int) -> str:\n    match x:\n        case 0: return "zero"\n        case _: return "other"',
    "type() builtin": 'def get_type(x):\n    return type(x)',
    "hasattr": 'def has(obj, name: str) -> bool:\n    return hasattr(obj, name)',
    "setattr": 'def setter(obj, name: str, val):\n    setattr(obj, name, val)',
    "map()": 'def double(items):\n    return list(map(lambda x: x * 2, items))',
    "filter()": 'def evens(items):\n    return list(filter(lambda x: x % 2 == 0, items))',
    "os.path.join": 'def make_path(a: str, b: str) -> str:\n    return os.path.join(a, b)',
    "os.path.exists": 'def check(p: str) -> bool:\n    return os.path.exists(p)',
    "os.makedirs": 'def ensure(p: str):\n    os.makedirs(p, exist_ok=True)',
    "os.listdir": 'def ls(p: str):\n    return os.listdir(p)',
    "os.environ.get": 'def env(key: str) -> str:\n    return os.environ.get(key, "")',
    "json.loads": 'def parse(s: str):\n    return json.loads(s)',
    "json.dumps": 'def serialize(d: dict) -> str:\n    return json.dumps(d)',
    "re.search": 'def has_match(pattern: str, text: str) -> bool:\n    return re.search(pattern, text) is not None',
    "re.findall": 'def find(pattern: str, text: str):\n    return re.findall(pattern, text)',
    "re.sub": 'def replace(pattern: str, repl: str, text: str) -> str:\n    return re.sub(pattern, repl, text)',
    "math.sqrt": 'def sq(x: float) -> float:\n    return math.sqrt(x)',
    "math.floor/ceil": 'def bounds(x: float):\n    return (math.floor(x), math.ceil(x))',
    "math.pi constant": 'def circle_area(r: float) -> float:\n    return math.pi * r * r',
    "random.choice": 'def pick(items):\n    return random.choice(items)',
    "random.randint": 'def roll(a: int, b: int) -> int:\n    return random.randint(a, b)',
    "string slicing": 'def first_three(s: str) -> str:\n    return s[:3]',
    "negative indexing": 'def last(items):\n    return items[-1]',
    "dict .keys()": 'def get_keys(d: dict):\n    return list(d.keys())',
    "dict .values()": 'def get_vals(d: dict):\n    return list(d.values())',
    "dict .items()": 'def get_items(d: dict):\n    return list(d.items())',
    "dict .update()": 'def merge(a: dict, b: dict):\n    a.update(b)',
    "dict .pop()": 'def take(d: dict, key: str):\n    return d.pop(key)',
    "list .insert()": 'def add(items, idx: int, val):\n    items.insert(idx, val)',
    "list .remove()": 'def rm(items, val):\n    items.remove(val)',
    "list .pop()": 'def take(items):\n    return items.pop()',
    "list .sort()": 'def order(items):\n    items.sort()',
    "list .reverse()": 'def flip(items):\n    items.reverse()',
    "not operator": 'def negate(x: bool) -> bool:\n    return not x',
    "chained compare": 'def in_range(x: int) -> bool:\n    return 0 < x < 100',
    "multiline string": 'def help_text() -> str:\n    return """This is\nmultiline"""',
    "decorator (ignored)": '@staticmethod\ndef helper() -> int:\n    return 42',
    "default param": 'def greet(name: str = "World") -> str:\n    return f"Hello {name}"',
    "**kwargs": 'def log(**kwargs):\n    print(kwargs)',
    "*args": 'def total(*args):\n    return sum(args)',
    "exception raise": 'def fail():\n    raise ValueError("bad")',
    "yield (generator)": 'def gen(n: int):\n    for i in range(n):\n        yield i',
}

ok_count = 0
weak_count = 0
for name, code in tests.items():
    try:
        rust = transpile_function_code(code)
    except Exception as e:
        print(f"  [CRASH] {name}: {e}")
        weak_count += 1
        continue
    has_todo = "todo!" in rust
    has_unmapped = "Unmapped" in rust
    status = "WEAK" if (has_todo or has_unmapped) else "OK"
    if status == "OK":
        ok_count += 1
    else:
        weak_count += 1
    print(f"  [{status:5s}] {name}")
    if status == "WEAK":
        for line in rust.split("\n"):
            if "todo!" in line or "Unmapped" in line:
                print(f"           {line.strip()}")

print(f"\n{'='*60}")
print(f"  Audit: {ok_count} OK, {weak_count} WEAK out of {ok_count + weak_count}")
print(f"{'='*60}")
