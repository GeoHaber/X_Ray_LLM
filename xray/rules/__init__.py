"""
X-Ray Pattern Rules — Built from real bugs found in production code.
Each rule has: id, severity, pattern (regex), description, fix_hint, test_hint.
"""

from .portability import PORTABILITY_RULES
from .python_rules import PYTHON_RULES
from .quality import QUALITY_RULES
from .security import SECURITY_RULES

ALL_RULES = SECURITY_RULES + QUALITY_RULES + PYTHON_RULES + PORTABILITY_RULES

__all__ = ["ALL_RULES", "PORTABILITY_RULES", "PYTHON_RULES", "QUALITY_RULES", "SECURITY_RULES"]
