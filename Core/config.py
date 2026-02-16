
from .utils import UNICODE_OK

__version__ = "4.1.0"

# Safe separator: always ASCII dash — renders correctly on every terminal/console
SEP = "-"

BANNER = f"""
{'='*64}
  X-RAY Claude v{__version__} — Smart AI Code Analyzer
  Powered by AST heuristics + optional Local LLM
{'='*64}
"""

# Thresholds (tunable)
SMELL_THRESHOLDS = {
    "long_function": 60,        # lines
    "very_long_function": 120,  # lines → critical
    "deep_nesting": 4,          # levels
    "very_deep_nesting": 6,     # levels → critical
    "high_complexity": 10,      # cyclomatic
    "very_high_complexity": 20, # cyclomatic → critical
    "too_many_params": 6,       # parameters
    "god_class": 15,            # methods
    "large_class": 500,         # lines
    "missing_docstring_size": 15,  # only flag if function > N lines
    "too_many_returns": 5,      # return statements
    "too_many_branches": 8,     # if/elif branches
}
