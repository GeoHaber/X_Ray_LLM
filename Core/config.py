import builtins as _builtins_mod

__version__ = "7.0.0"

# Safe separator: always ASCII dash — renders correctly on every terminal/console
SEP = "-"

BANNER = f"""
{"=" * 64}
  X-RAY Claude v{__version__} — Universal Code Quality Scanner
  Python + JS/TS/React | AST Smells | Ruff | Bandit | Health
{"=" * 64}
"""

# Thresholds (tunable)
SMELL_THRESHOLDS = {
    "long_function": 100,  # lines (85 still caught utility builders; 100 aligns with PEP8 spirit)
    "very_long_function": 150,  # lines → critical (raised proportionally)
    "deep_nesting": 6,  # levels (5 is too aggressive for AST visitors; 6 is standard)
    "very_deep_nesting": 8,  # levels → critical (AST visitor methods legitimately reach 7)
    "high_complexity": 16,  # cyclomatic (15 caught dispatch functions; 16 is strict-but-fair)
    "very_high_complexity": 20,  # cyclomatic → critical
    "too_many_params": 8,  # parameters (7 triggered on stdlib-like helpers with ctx args)
    "god_class": 20,  # methods (Mixin and Test classes are exempt)
    "large_class": 500,  # lines
    "missing_docstring_size": 25,  # only flag if function > N lines
    "too_many_returns": 8,  # return statements (type-dispatch functions legitimately hit 7)
    "too_many_branches": 10,  # if/elif branches (visitor/dispatcher methods hit 8-9)
    # ── new in v6.0.0 ────────────────────────────────────────────────────
    "magic_number_min_count": 6,  # flag if ≥ N distinct magic numbers in a function
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
    except Exception:  # nosec B110
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
        "dist",
        "Lib",
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
        # Generated test artefacts — machine-made, not representative of production quality
        "xray_generated",
        "_generated_tests",
        # Rust transpiler output dirs — machine-generated, like xray_generated
        "_rustified",
        "_rustified_exe_build",
    }
)

_BUILTIN_NAMES = frozenset(dir(_builtins_mod))

_STOP_WORDS = frozenset(
    "self cls none true false return def class if else elif for while try "
    "except finally with as import from raise pass break continue yield "
    "lambda and or not in is assert del global nonlocal async await "
    "the a an of to is it that this be on at by do has was are were "
    "str int float bool list dict set tuple bytes type any all len "
    "range print open super init new call".split()
)
