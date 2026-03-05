"""Auto-generated project structure tests by X-Ray v7.0.

Verifies essential files & directories exist.
"""

from pathlib import Path


ROOT = Path(__file__).parent.parent.resolve()





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
