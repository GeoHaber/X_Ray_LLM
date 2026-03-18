"""
Portability rules — Detect hardcoded paths, user-specific paths,
and non-portable directory references that break across machines.

Sourced from real portability failures across 16 projects.
"""

# NOTE: Regex patterns use raw strings. Some are split via concatenation
# to avoid self-matching during scans.

PORTABILITY_RULES = [
    {
        "id": "PORT-001",
        "severity": "HIGH",
        "lang": ["python"],
        "pattern": (
            r"""(?:Path|path|=\s*r?['"]).{0,5}C:[/\\]Users[/\\]\w+"""
        ),
        "description": "Hardcoded user-specific path — breaks on any other machine",
        "fix_hint": (
            "Replace with Path.home() or os.environ.get('ENV_VAR', fallback). "
            "For test fixtures use Path(__file__).resolve().parent / 'subdir'"
        ),
        "test_hint": "Verify no C:\\Users\\<username> paths exist in production code",
    },
    {
        "id": "PORT-002",
        "severity": "HIGH",
        "lang": ["python"],
        "pattern": (
            r"""(?:Path|path|=\s*r?['"]).{0,5}C:[/\\]AI[/\\]"""
        ),
        "description": (
            "Hardcoded C:\\AI\\ path — not portable; "
            "use ZENAI_MODEL_DIR env var or Path.home() / 'AI' fallback"
        ),
        "fix_hint": (
            "Use os.environ.get('ZENAI_MODEL_DIR', str(Path.home() / 'AI' / 'Models'))"
        ),
        "test_hint": "Verify model/binary paths use env vars with home-based fallbacks",
    },
    {
        "id": "PORT-003",
        "severity": "MEDIUM",
        "lang": ["python"],
        "pattern": (
            r"""(?:Path|os\.chdir|open)\s*\(\s*r?['"](?:"""
            r"""[A-Z]:[/\\](?!Users[/\\]|AI[/\\]|Windows[/\\]|Program)"""
            r""")[^'"]{5,}['"]"""
        ),
        "description": (
            "Hardcoded absolute Windows path — not portable to Linux/macOS"
        ),
        "fix_hint": (
            "Use Path(__file__).parent-relative paths or environment variables"
        ),
        "test_hint": "Verify no hardcoded drive-letter paths outside standard system dirs",
    },
    {
        "id": "PORT-004",
        "severity": "MEDIUM",
        "lang": ["python"],
        "pattern": (
            r"""(?:import\s+winreg|import\s+msvcrt|from\s+ctypes\.wintypes\s+import)"""
        ),
        "description": (
            "Windows-only module import — will crash on Linux/macOS "
            "unless guarded by platform check"
        ),
        "fix_hint": (
            "Guard with: if platform.system() == 'Windows': import winreg  "
            "or use try/except ImportError"
        ),
        "test_hint": "Verify Windows-only imports are guarded by platform checks or try/except",
    },
]
