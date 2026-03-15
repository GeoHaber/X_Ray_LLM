"""
Python-specific anti-pattern rules.
Sourced from real bugs found during X-Ray audits.
"""

PYTHON_RULES = [
    {
        "id": "PY-001",
        "severity": "MEDIUM",
        "lang": ["python"],
        "pattern": r"def\s+\w+\(.*\)\s*->\s*None:.*\n.*return\s+\{",
        "description": "Function annotated as -> None but returns a dict",
        "fix_hint": "Fix the return type annotation to match actual return value",
        "test_hint": "Verify function return types match their annotations",
    },
    {
        "id": "PY-002",
        "severity": "HIGH",
        "lang": ["python"],
        "pattern": r"def\s+\w+\([^)]*\bself\b[^)]*\).*\n(?:.*\n)*?.*\bself\.\w+\(.*\)\.items\(\)",
        "description": "Calling .items() on method that returns None (common in HTTP handlers)",
        "fix_hint": "Check if the method returns a dict or None before calling .items()",
        "test_hint": "Test that methods returning None are not iterated with .items()",
    },
    {
        "id": "PY-003",
        "severity": "MEDIUM",
        "lang": ["python"],
        "pattern": r"import\s+\*|from\s+\w+\s+import\s+\*",
        "description": "Wildcard import pollutes namespace and hides dependencies",
        "fix_hint": "Import specific names: from module import func1, func2",
        "test_hint": "Verify no wildcard imports exist in production code",
    },
    {
        "id": "PY-004",
        "severity": "LOW",
        "lang": ["python"],
        "pattern": r"print\s*\(",
        "description": "Debug print statement left in code — use logging instead",
        "fix_hint": "Replace print() with logging.debug/info/warning as appropriate",
        "test_hint": "Verify production code uses logging module instead of print()",
    },
    {
        "id": "PY-005",
        "severity": "HIGH",
        "lang": ["python"],
        "pattern": r"(json\.loads|json\.load)\([^)]+\)(?!\s*#\s*nosec)(?!.*try|.*except)",
        "description": "JSON parsing without error handling — crashes on malformed input",
        "fix_hint": "Wrap json.loads() in try/except json.JSONDecodeError",
        "test_hint": "Test that malformed JSON input returns an error response, not a crash",
    },
    {
        "id": "PY-006",
        "severity": "MEDIUM",
        "lang": ["python"],
        "pattern": r"global\s+\w+",
        "description": "Global variable mutation — hard to test and reason about",
        "fix_hint": "Pass state through function parameters or use a class",
        "test_hint": "Verify global state is minimized and thread-safe if concurrent",
    },
    {
        "id": "PY-007",
        "severity": "MEDIUM",
        "lang": ["python"],
        "pattern": r"os\.environ\[",
        "description": "Direct os.environ[] access crashes on missing key — use .get() with default",
        "fix_hint": "Use os.environ.get('KEY', 'default') instead of os.environ['KEY']",
        "test_hint": "Verify environment variable access has defaults for missing keys",
    },
    {
        "id": "PY-008",
        "severity": "MEDIUM",
        "lang": ["python"],
        "pattern": r"\bopen\((?![^)]*(?:encoding|['\"]r?b['\"]))[^)]+\)",
        "description": "File opened without explicit encoding — platform-dependent behavior",
        "fix_hint": "Always specify encoding='utf-8' for text file operations",
        "test_hint": "Verify all text file opens specify explicit encoding",
    },
]
