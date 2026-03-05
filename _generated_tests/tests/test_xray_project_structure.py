"""Auto-generated project structure tests by X-Ray v7.0.

Verifies essential files & directories exist.
"""

from pathlib import Path


ROOT = Path(__file__).parent.parent.resolve()

def test_project_has__gitignore():
    """Structure: .gitignore should exist at project root."""
    assert (ROOT / ".gitignore").exists(), "Missing .gitignore"

def test_project_has_README_md():
    """Structure: README.md should exist at project root."""
    assert (ROOT / "README.md").exists(), "Missing README.md"

def test_project_has_requirements_txt():
    """Structure: requirements.txt should exist at project root."""
    assert (ROOT / "requirements.txt").exists(), "Missing requirements.txt"

def test_project_has_tests_dir():
    """Structure: tests/ directory should exist."""
    assert (ROOT / "tests").is_dir(), "Missing tests/ directory"

def test_no_python_syntax_errors():
    """Verify all .py files can be compiled without SyntaxError."""
    import py_compile
    errors = []
    for pyfile in ROOT.rglob("*.py"):
        if any(part.startswith(".") or part in ("__pycache__", ".venv", "venv", "node_modules")
               for part in pyfile.parts):
            continue
        try:
            py_compile.compile(str(pyfile), doraise=True)
        except py_compile.PyCompileError as e:
            errors.append(str(e))
    assert not errors, f"Syntax errors in {len(errors)} files:\n" + "\n".join(errors[:5])
