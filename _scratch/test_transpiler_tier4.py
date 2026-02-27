"""
Tests for Tier-4 transpiler type improvements:
  - Owned types for parameters (String, Vec, HashMap instead of &str, &[T], &HashMap)
  - Single-letter variable types (i→i64, x→f64)
  - Option<T> return wrapping (Some(val), None)
  - Path() → PathBuf::from()
  - Subscript index casting (as usize for BinOp/int())
  - Float-aware BinOp return inference
  - Constructor mapping (set, frozenset, bytearray, Exception)
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from Analysis.transpiler import transpile_function_code
import traceback

PASS = 0
FAIL = 0

def check(label: str, code: str, must_contain: list[str], must_not_contain: list[str] = None):
    global PASS, FAIL
    must_not_contain = must_not_contain or []
    try:
        rust = transpile_function_code(code)
    except Exception as e:
        FAIL += 1
        print(f"  [FAIL] {label}: EXCEPTION {e}")
        traceback.print_exc()
        return

    ok = True
    for needle in must_contain:
        if needle not in rust:
            print(f"  [FAIL] {label}: missing '{needle}'")
            print(f"         Output: {rust[:400]}")
            ok = False
            break
    for needle in must_not_contain:
        if needle in rust:
            print(f"  [FAIL] {label}: should NOT contain '{needle}'")
            print(f"         Output: {rust[:400]}")
            ok = False
            break
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1


# ── Owned parameter types ───────────────────────────────────────────

print("\n=== Owned parameter types (no &str) ===")

check("text param → String",
      "def greet(text):\n    return text",
      ["text: String"],
      must_not_contain=["&str"])

check("name param → String",
      "def hello(name):\n    print(name)",
      ["name: String"],
      must_not_contain=["&str"])

check("path param → String",
      "def read(file_path):\n    return open(file_path)",
      ["file_path: String"],
      must_not_contain=["&str"])

check("items param → Vec<String>",
      "def process(items):\n    for i in items:\n        pass",
      ["items: Vec<String>"],
      must_not_contain=["&[String]"])

check("config param → HashMap",
      "def setup(config):\n    return config",
      ["config: HashMap<String, String>"],
      must_not_contain=["&HashMap"])

check("default param → String",
      "def run(data):\n    return data",
      ["data: String"],
      must_not_contain=["&str"])


# ── Single-letter variable types ────────────────────────────────────

print("\n=== Single-letter variable types ===")

check("i param → i64",
      "def at(i):\n    return i",
      ["i: i64"],
      must_not_contain=["usize"])

check("n param → i64",
      "def repeat(n):\n    return n * 2",
      ["n: i64"],
      must_not_contain=["usize"])

check("x param → f64",
      "def scale(x):\n    return x * 2.0",
      ["x: f64"])

check("j param → i64",
      "def loop_idx(j):\n    return j + 1",
      ["j: i64"])

check("count param → i64",
      "def tally(count):\n    return count + 1",
      ["count: i64"],
      must_not_contain=["usize"])

check("timeout param → f64",
      "def wait(timeout):\n    pass",
      ["timeout: f64"])


# ── Option<T> return wrapping ───────────────────────────────────────

print("\n=== Option<T> return wrapping ===")

check("Optional[str] returns Some()",
      "def find(text: str) -> Optional[str]:\n    if text:\n        return text\n    return None",
      ["-> Option<String>", "Some(", "return None;"])

check("Optional[int] returns Some()",
      "def parse(s: str) -> Optional[int]:\n    return int(s)",
      ["-> Option<i64>", "Some("])

check("non-Optional returns no Some()",
      "def add(a: int, b: int) -> int:\n    return a + b",
      ["-> i64"],
      must_not_contain=["Some(", "Option"])


# ── Path() → PathBuf::from() ───────────────────────────────────────

print("\n=== Path constructor ===")

check("Path(x) → PathBuf::from(x)",
      "def make_path(s):\n    return Path(s)",
      ["PathBuf::from("],
      must_not_contain=["Path(s)"])

check("Path() no args → PathBuf::new()",
      "def empty_path():\n    return Path()",
      ["PathBuf::new()"])


# ── Subscript index casting ─────────────────────────────────────────

print("\n=== Subscript index casting ===")

check("arr[int(x)] → as usize",
      "def at(arr, x):\n    return arr[int(x)]",
      ["as usize"])

check("arr[a + b] → as usize (BinOp index)",
      "def at(arr, a: int, b: int):\n    return arr[a + b]",
      ["as usize"])

check("arr[0] → no cast (literal)",
      "def first(arr):\n    return arr[0]",
      ["arr[0]"],
      must_not_contain=["as usize"])


# ── Float-aware BinOp return inference ──────────────────────────────

print("\n=== Float BinOp return type ===")

check("float * float → f64 return",
      "def area(w: float, h: float):\n    return w * h",
      ["-> f64"])

check("int + int → i64 return",
      "def add(a: int, b: int):\n    return a + b",
      ["-> i64"])


# ── Constructor mapping ─────────────────────────────────────────────

print("\n=== Constructor mapping ===")

check("set() → HashSet::new()",
      "def empty():\n    return set()",
      ["HashSet::new()"])

check("set(items) → collect into HashSet",
      "def uniq(items):\n    return set(items)",
      ["collect::<HashSet<_>>()"])


# ── Summary ─────────────────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"  Tier-4 Results: {PASS} passed, {FAIL} failed out of {PASS+FAIL}")
print(f"{'='*50}")
if FAIL == 0:
    print("  ALL TESTS PASSED!")
else:
    print(f"  {FAIL} FAILURES — review above")
    sys.exit(1)
