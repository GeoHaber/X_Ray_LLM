__version__ = "5.0.0"

# Safe separator: always ASCII dash — renders correctly on every terminal/console
SEP = "-"

BANNER = f"""
{"=" * 64}
  X-RAY Claude v{__version__} — Unified Code Quality Scanner
  AST Smells + Ruff Lint + Bandit Security
{"=" * 64}
"""

# Thresholds (tunable)
SMELL_THRESHOLDS = {
    "long_function": 60,  # lines
    "very_long_function": 120,  # lines → critical
    "deep_nesting": 4,  # levels
    "very_deep_nesting": 6,  # levels → critical
    "high_complexity": 10,  # cyclomatic
    "very_high_complexity": 20,  # cyclomatic → critical
    "too_many_params": 6,  # parameters
    "god_class": 15,  # methods
    "large_class": 500,  # lines
    "missing_docstring_size": 15,  # only flag if function > N lines
    "too_many_returns": 5,  # return statements
    "too_many_branches": 8,  # if/elif branches
}

# LLM Settings (Centralized — overridden by xray_settings.json if present)
LLM_CONFIG = {
    "base_url": "http://localhost:8080/v1",
    "api_key": "sk-placeholder",
    "model": "local-model",
    "timeout": 60,
    "max_tokens": 1024,
    "temperature": 0.7,
}


def load_llm_config():
    """Merge LLM_CONFIG with persisted settings from xray_settings.json."""
    try:
        from .llm_manager import load_settings

        settings = load_settings()
        llm = settings.get("llm", {})
        if llm.get("server_url"):
            LLM_CONFIG["base_url"] = llm["server_url"]
        if llm.get("api_key"):
            LLM_CONFIG["api_key"] = llm["api_key"]
        if llm.get("model_id"):
            LLM_CONFIG["model"] = llm["model_id"]
        if llm.get("temperature"):
            LLM_CONFIG["temperature"] = llm["temperature"]
        if llm.get("max_tokens"):
            LLM_CONFIG["max_tokens"] = llm["max_tokens"]
        if llm.get("context_size"):
            LLM_CONFIG["timeout"] = max(60, llm.get("context_size", 4096) // 50)
    except Exception:
        pass  # settings file doesn't exist yet — use defaults


_ALWAYS_SKIP = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".tox",
        ".nox",
        ".eggs",
        "node_modules",
        "venv",
        ".venv",
        "env",
        ".env",
        "site-packages",
        "dist-packages",
        "_archive",
        "_Old",
        "_old",
        "_bin",
        "_scratch",
        ".github",
        "portable",
        "target",
        "build_exe",
        "build_web",
        "X_Ray_Desktop",
        "X_Ray_Standalone",
        "X_Ray_Rust_Full",
    }
)

import builtins as _builtins_mod  # noqa: E402

_BUILTIN_NAMES = frozenset(dir(_builtins_mod))

_STOP_WORDS = frozenset(
    "self cls none true false return def class if else elif for while try "
    "except finally with as import from raise pass break continue yield "
    "lambda and or not in is assert del global nonlocal async await "
    "the a an of to is it that this be on at by do has was are were "
    "str int float bool list dict set tuple bytes type any all len "
    "range print open super init new call".split()
)
