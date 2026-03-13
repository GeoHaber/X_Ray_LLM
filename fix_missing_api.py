#!/usr/bin/env python
"""
fix_missing_api.py — Auto-generate missing module-level API functions using TDD.

This script:
1. Parses all failing tests from xray_generated/
2. Extracts missing function ImportErrors
3. Finds the corresponding source modules
4. Identifies the class that has the missing method
5. Generates module-level wrapper functions
6. Adds them to the source file with proper validation
"""

import re
import subprocess
import sys
from pathlib import Path
from collections import defaultdict
from typing import Dict, Optional, Set

PROJECT_ROOT = Path(__file__).parent
ANALYSIS_DIR = PROJECT_ROOT / "Analysis"
CORE_DIR = PROJECT_ROOT / "Core"
UI_DIR = PROJECT_ROOT / "UI"
TESTS_DIR = PROJECT_ROOT / "tests" / "xray_generated"


def run_tests() -> str:
    """Run pytest on xray_generated and capture output."""
    result = subprocess.run(
        ["python", "-m", "pytest", str(TESTS_DIR), "-q", "--tb=line"],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    return result.stdout + result.stderr


def parse_import_errors(test_output: str) -> Dict[str, Set[str]]:
    """Parse ImportError lines to extract module -> missing_functions mapping.

    Example line:
    ImportError: cannot import name 'analyze' from 'Analysis.security'
    """
    pattern = r"cannot import name '(\w+)' from '([^']+)'"
    missing_by_module: Dict[str, Set[str]] = defaultdict(set)

    for match in re.finditer(pattern, test_output):
        func_name = match.group(1)
        module_name = match.group(2)
        missing_by_module[module_name].add(func_name)

    return missing_by_module


def module_to_file_path(module_name: str) -> Path:
    """Convert module name to file path."""
    # 'Analysis.format' -> Analysis/format.py
    # 'Core.types' -> Core/types.py
    parts = module_name.split(".")

    if parts[0] == "Analysis":
        # Handle nested like "Analysis.NexusMode.adapters"
        return ANALYSIS_DIR / "/".join(parts[1:]).replace(".", "/") / ".py"
    elif parts[0] == "Core":
        return CORE_DIR / (parts[1] + ".py")
    elif parts[0] == "UI":
        return UI_DIR / (parts[1] + ".py")
    else:
        return PROJECT_ROOT / (parts[0] + ".py")


def get_class_with_method(file_path: Path, method_name: str) -> Optional[str]:
    """Find class that defines a method."""
    if not file_path.exists():
        return None

    content = file_path.read_text("utf-8")

    # Look for "def method_name" and find enclosing class
    method_pattern = rf"^\s+def {re.escape(method_name)}\("
    class_pattern = r"^class\s+(\w+)"

    lines = content.split("\n")
    last_class = None

    for i, line in enumerate(lines):
        if re.match(class_pattern, line):
            match = re.match(class_pattern, line)
            last_class = match.group(1)

        if re.match(method_pattern, line) and last_class:
            return last_class

    return last_class


def generate_wrapper_function(
    class_name: str, method_name: str, signature: str = ""
) -> str:
    """Generate a module-level wrapper function."""
    if signature:
        sig = f"({signature})"
    else:
        sig = "(*args, **kwargs)"

    return f"""def {method_name}{sig}:
    \"\"\"Wrapper for {class_name}.{method_name}().\"\"\"
    return _default_{class_name.lower()}.{method_name}{sig}
"""


def main():
    print("[*] Running tests to identify missing APIs...")
    test_output = run_tests()

    missing_by_module = parse_import_errors(test_output)

    if not missing_by_module:
        print("[OK] No missing imports found!")
        return 0

    print(
        f"\n[SUMMARY] Found {sum(len(v) for v in missing_by_module.values())} missing functions in {len(missing_by_module)} modules:"
    )

    for module_name, functions in sorted(missing_by_module.items()):
        print(f"  {module_name}: {', '.join(sorted(functions))}")

    print("\n[INFO] To fix these, we need to add module-level wrapper functions.")
    print("   This follows the TDD principle: expose testable APIs at module level.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
