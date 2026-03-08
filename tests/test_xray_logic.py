import pytest
from pathlib import Path
import sys

# Ensure X_Ray is in path if not already
XRAY_ROOT = str(Path(__file__).parent.parent)
if XRAY_ROOT not in sys.path:
    sys.path.insert(0, XRAY_ROOT)

from Analysis.ast_utils import extract_functions_from_file
from Analysis.smells import CodeSmellDetector
from Analysis.duplicates import DuplicateFinder
from Analysis.rust_advisor import RustAdvisor

# --- FIXTURES ---

@pytest.fixture
def temp_root(tmp_path):
    """Create a temporary project root."""
    return tmp_path

# --- AST TESTS ---

def test_extract_functions_and_classes(temp_root):
    code = """
def hello(name: str) -> str:
    \"\"\"Greeting function.\"\"\"
    return f"Hello {name}"

class MyClass:
    \"\"\"A simple class.\"\"\"
    def __init__(self):
        self.val = 1
    
    def method_one(self):
        return self.val
    """
    fpath = temp_root / "sample.py"
    fpath.write_text(code)
    
    funcs, classes, err = extract_functions_from_file(fpath, temp_root)
    
    assert err is None
    assert len(funcs) == 3  # hello, __init__, method_one
    assert len(classes) == 1
    
    hello_func = next(f for f in funcs if f.name == "hello")
    assert hello_func.parameters == ["name"]
    assert hello_func.return_type == "str"
    assert "Greeting function" in hello_func.docstring
    
    cls = classes[0]
    assert cls.name == "MyClass"
    assert cls.method_count == 2
    assert "__init__" in cls.methods

# --- SMELL TESTS ---

def test_smell_detection_logic(temp_root):
    code = """
def smelly_function(a, b, c, d, e, f, g, h, i):
    # 9 params (limit 8)
    x = 42 
    y = 43
    z = 44
    w = 45
    k = 46
    m = 47 # 6 magic numbers (limit 6)
    if a:
        if b:
            if c:
                if d:
                    if e:
                        if f:
                            print("Deep nesting") # 6 levels (limit 6)
    return x

def mutable_default(x=[]):
    return x

def dead_code():
    return True
    print("Unreachable")
    """
    fpath = temp_root / "smells.py"
    fpath.write_text(code)
    
    funcs, classes, _ = extract_functions_from_file(fpath, temp_root)
    # Use default thresholds explicitly to ensure triggers
    detector = CodeSmellDetector()
    smells = detector.detect(funcs, classes)
    
    categories = [s.category for s in smells]
    
    # Debug print if failed
    if "too-many-params" not in categories:
        print(f"Categories found: {categories}")
        
    assert "too-many-params" in categories
    assert "magic-number" in categories
    assert "deep-nesting" in categories
    assert "mutable-default-arg" in categories
    assert "dead-code" in categories

# --- DUPLICATE TESTS ---

def test_duplicate_finding(temp_root):
    code1 = """
def logic_heavy_a(x, y, z):
    \"\"\"Some docstring to increase size.\"\"\"
    res = x + y + z
    res = res * 2
    res = res / 3
    res = res + 10
    res = res - 5
    return f"Result is {res}"
    """
    code2 = """
def logic_heavy_b(a, b, c):
    \"\"\"Different docstring, same logic.\"\"\"
    val = a + b + c
    val = val * 2
    val = val / 3
    val = val + 10
    val = val - 5
    return f"Result is {val}"
    """
    (temp_root / "file1.py").write_text(code1)
    (temp_root / "file2.py").write_text(code2)
    
    funcs1, _, _ = extract_functions_from_file(temp_root / "file1.py", temp_root)
    funcs2, _, _ = extract_functions_from_file(temp_root / "file2.py", temp_root)
    
    all_funcs = funcs1 + funcs2
    finder = DuplicateFinder()
    # Force minimal line limit to ensure short funcs are caught
    finder.SEMANTIC_MIN_LINES = 1
    groups = finder.find(all_funcs)
    
    assert len(groups) >= 1
    # Structural match should catch logic_heavy_a and logic_heavy_b
    assert any(g.similarity_type == "structural" for g in groups)

# --- RUST ADVISOR TESTS ---

def test_rust_advisor_scoring(temp_root):
    code = """
def intensive_math(n):
    res = 0
    for i in range(n):
        for j in range(n):
            res += i * j
    return res
    """
    fpath = temp_root / "math_heavy.py"
    fpath.write_text(code)
    
    funcs, _, _ = extract_functions_from_file(fpath, temp_root)
    advisor = RustAdvisor()
    candidates = advisor.score(funcs)
    
    assert len(candidates) > 0
    # Use .func.name instead of .name
    assert candidates[0].func.name == "intensive_math"
    assert candidates[0].score > 0
