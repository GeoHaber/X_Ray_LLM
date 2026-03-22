"""
Shared constants used across the X-Ray codebase.

Centralises skip-directories, text extensions, and utility helpers
that were previously duplicated in 3-5 modules.
"""

# ── Directories to skip during scans / analysis ─────────────────────────
SKIP_DIRS: frozenset[str] = frozenset({
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "env",
    ".env",
    "node_modules",
    ".tox",
    "build",
    "dist",
    "_rustified",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "target",
    "eggs",
    "*.egg-info",
    "egg-info",
    ".eggs",
    "site-packages",
    "_OLD_JUNK",
})

# ── Text file extensions (for grep-style searches) ──────────────────────
TEXT_EXTS: frozenset[str] = frozenset({
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".java", ".c", ".cpp", ".h", ".cs",
    ".go", ".rb", ".rs", ".sh", ".bat",
    ".yaml", ".yml", ".toml", ".md",
})

PY_EXTS: frozenset[str] = frozenset({".py"})

WEB_EXTS: frozenset[str] = frozenset({
    ".js", ".ts", ".jsx", ".tsx",
    ".html", ".css", ".vue", ".svelte",
})


# ── Path normaliser ─────────────────────────────────────────────────────
def fwd(path: str) -> str:
    """Normalise a filesystem path to forward slashes."""
    return path.replace("\\", "/")
