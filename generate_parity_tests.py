import sys
from pathlib import Path

# Setup path
sys.path.insert(0, str(Path(__file__).parent))

from Analysis.test_gen import TestReferenceGenerator
from Lang.python_ast import ASTNormalizer


def pure_python_normalize(code: str) -> str:
    """
    The 'Ground Truth' function.
    Run the Python ASTNormalizer and return the unparsed code.
    """
    try:
        import ast
        import copy

        node = ast.parse(code)
        # Deep copy because NodeTransformer modifies in-place
        normalized = ASTNormalizer().visit(copy.deepcopy(node))
        return ast.unparse(normalized)
    except Exception as e:
        return f"ERROR: {e}"


def main():
    """Generate parity test cases to verify Rust matches Python output."""
    print("🚀 Generating Parity Tests for Variable Renaming")

    gen = TestReferenceGenerator(pure_python_normalize)

    # Hand-crafted edge cases for variable renaming
    vectors = [
        # Basic argument renaming
        {"args": ["def func(a, b): return a + b"], "kwargs": {}},
        # Local variable renaming
        {"args": ["def func():\n    x = 1\n    y = 2\n    return x + y"], "kwargs": {}},
        # Variable vs Argument masking
        {"args": ["def func(x):\n    x = x + 1\n    return x"], "kwargs": {}},
        # Docstring stripping check
        {"args": ['def func():\n    """Docstring"""\n    pass'], "kwargs": {}},
        # Complex mix
        {
            "args": [
                "def calc(price, tax):\n    total = price * (1 + tax)\n    return total"
            ],
            "kwargs": {},
        },
    ]

    # Optional: Ask LLM for more if needed
    # vectors.extend(gen.generate_llm_vectors(count=2))

    print(f"✅ Prepared {len(vectors)} input vectors.")
    results = gen.capture_ground_truth(vectors)

    fixture_path = gen.save_fixture(results)
    print(f"💾 Saved test fixture to: {fixture_path}")


if __name__ == "__main__":
    main()
