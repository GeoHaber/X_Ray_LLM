//! Shared constants used across the X-Ray codebase.
//! Rust port of xray/constants.py.

/// Directories to skip during scans / analysis.
pub const SKIP_DIRS: &[&str] = &[
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
];

/// Text file extensions (for grep-style searches).
pub const TEXT_EXTS: &[&str] = &[
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h",
    ".cs", ".go", ".rb", ".rs", ".sh", ".bat", ".yaml", ".yml", ".toml", ".md",
];

/// Python file extensions.
pub const PY_EXTS: &[&str] = &[".py"];

/// Web file extensions.
pub const WEB_EXTS: &[&str] = &[
    ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".vue", ".svelte",
];
