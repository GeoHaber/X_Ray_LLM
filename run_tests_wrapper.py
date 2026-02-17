
import sys
import pytest
from pathlib import Path

# Add current directory (project root) to sys.path
root = Path(__file__).parent.resolve()
sys.path.insert(0, str(root))
print(f"Running tests with PYTHONPATH set to: {root}")



# Run ALL tests
test_dir = root / "tests"
print(f"Running all tests in: {test_dir}")

if __name__ == "__main__":
    # We use "-v" and also ignore the 'rust_harness' which might need compilation
    exit_code = pytest.main([str(test_dir), "-v", "--ignore=tests/rust_harness"])
    sys.exit(exit_code)
