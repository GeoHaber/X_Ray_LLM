"""Test the expanded transpiler capabilities."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Analysis.transpiler import transpile_function_code

tests = {}

# Test 1: for loops (was blocked by " for " marker, now unlocked)
tests["for loops"] = '''
def sum_list(items: list) -> int:
    total = 0
    for x in items:
        total += x
    return total
'''

# Test 2: list comprehension (was blocked by pattern check)
tests["comprehension"] = '''
def squares(n: int) -> list:
    return [x * x for x in range(n)]
'''

# Test 3: lambda (was blocked by "lambda " marker)
tests["lambda"] = '''
def apply_fn(items: list) -> list:
    return sorted(items, key=lambda x: x * 2)
'''

# Test 4: re module (NEW handler)
tests["re module"] = '''
def find_numbers(text: str) -> list:
    import re
    matches = re.findall(r"\\d+", text)
    if re.search(r"hello", text):
        text = re.sub(r"world", "rust", text)
    return matches
'''

# Test 5: json module (NEW handler)
tests["json module"] = '''
def parse_config(data: str) -> dict:
    import json
    config = json.loads(data)
    output = json.dumps(config)
    return config
'''

# Test 6: try/except → Result (UPGRADED from comments to real code)
tests["try/except"] = '''
def safe_parse(text: str) -> int:
    try:
        result = int(text)
        return result
    except ValueError as e:
        return -1
'''

# Test 7: try/except/finally
tests["try/finally"] = '''
def read_file(path: str) -> str:
    try:
        data = open(path)
        return data
    except Exception:
        return ""
    finally:
        print("done")
'''

# Test 8: nested function → closure (UPGRADED from // TODO to real closure)
tests["nested function"] = '''
def outer(x: int) -> int:
    def helper(y: int) -> int:
        return y * 2
    return helper(x) + 1
'''

# Test 9: nested class → struct (NEW)
tests["nested class"] = '''
def make_point():
    class Point:
        x: int
        y: int
        def distance(self) -> float:
            return (self.x ** 2 + self.y ** 2) ** 0.5
    return Point()
'''

# Test 10: match/case → Rust match (NEW, Python 3.10+)
tests["match/case"] = '''
def handle_command(cmd: str) -> str:
    match cmd:
        case "quit":
            return "exiting"
        case "hello":
            return "hi there"
        case _:
            return "unknown"
'''

# Test 11: math module (NEW)
tests["math module"] = '''
def compute(x: float) -> float:
    import math
    a = math.sqrt(x)
    b = math.log(x, 10)
    c = math.pi
    return a + b + c
'''

# Test 12: os.path module (NEW)
tests["os.path module"] = '''
def check_file(path: str) -> bool:
    import os.path
    if os.path.exists(path):
        name = os.path.basename(path)
        return True
    return False
'''

# Test 13: complex mixed (comprehensive)
tests["complex mixed"] = '''
def process_data(items: list, pattern: str) -> dict:
    import re
    import json
    results = {}
    for item in items:
        if re.search(pattern, item):
            try:
                parsed = json.loads(item)
                results[item] = parsed
            except Exception as e:
                results[item] = None
    return results
'''

# Run all tests
passed = 0
failed = 0
for name, code in tests.items():
    print(f"\n{'='*60}")
    print(f"  TEST: {name}")
    print(f"{'='*60}")
    try:
        result = transpile_function_code(code)
        print(result)
        # Basic quality checks
        has_todo = "// TODO" in result
        has_comment_only_try = "// try {" in result
        if has_todo and name not in ("nested class",):  # some TODOs are OK
            print(f"  [WARN] Contains // TODO markers")
        if has_comment_only_try:
            print(f"  [FAIL] try/except still comment-only!")
            failed += 1
        else:
            passed += 1
            print(f"  [OK]")
    except Exception as e:
        print(f"  [FAIL] Exception: {e}")
        failed += 1

print(f"\n{'='*60}")
print(f"  RESULTS: {passed} passed, {failed} failed out of {len(tests)}")
print(f"{'='*60}")
