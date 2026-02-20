
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

@dataclass
class FunctionRecord:
    """Extracted function metadata from AST."""
    name: str
    file_path: str          # relative path
    line_start: int
    line_end: int
    size_lines: int
    parameters: List[str]
    return_type: Optional[str]
    decorators: List[str]
    docstring: Optional[str]
    calls_to: List[str]
    complexity: int         # cyclomatic (if/for/while/try/except/assert/bool)
    nesting_depth: int      # max nesting level
    code_hash: str          # MD5 of function body
    structure_hash: str     # MD5 of normalized AST (for structural duplicates)
    code: str               # actual source code
    return_count: int = 0   # number of return statements
    branch_count: int = 0   # number of if/elif branches
    is_async: bool = False

    @property
    def key(self) -> str:
        from pathlib import Path
        p = Path(self.file_path)
        parent = str(p.parent).replace("\\", "/")
        stem = p.stem
        if parent == ".":
            return f"{stem}::{self.name}"
        return f"{parent}/{stem}::{self.name}"

    @property
    def location(self) -> str:
        return f"{self.file_path}:{self.line_start}"

    @property
    def signature(self) -> str:
        params = ", ".join(self.parameters)
        ret = f" -> {self.return_type}" if self.return_type else ""
        return f"{self.name}({params}){ret}"


@dataclass
class ClassRecord:
    """Extracted class metadata from AST."""
    name: str
    file_path: str
    line_start: int
    line_end: int
    size_lines: int
    method_count: int
    base_classes: List[str]
    docstring: Optional[str]
    methods: List[str]      # method names
    has_init: bool


@dataclass
class SmellIssue:
    """A detected code smell."""
    file_path: str
    line: int
    end_line: int
    category: str           # e.g. "long-function", "god-class", "deep-nesting"
    severity: str           # Severity.CRITICAL / WARNING / INFO
    message: str
    suggestion: str
    name: str               # function/class name
    metric_value: int = 0   # the number that triggered the smell (size, depth, etc.)
    llm_analysis: str = ""  # optional LLM-generated detailed analysis
    source: str = "xray"    # origin tool: "xray", "ruff", "bandit"
    rule_code: str = ""     # tool-specific rule id, e.g. "F401", "B602"
    fixable: bool = False   # whether the issue can be auto-fixed
    confidence: str = ""    # bandit confidence level: HIGH / MEDIUM / LOW


@dataclass
class DuplicateGroup:
    """A group of similar/duplicate functions."""
    group_id: int
    similarity_type: str    # "exact", "near", "semantic", "structural"
    avg_similarity: float
    functions: List[Dict[str, Any]]
    merge_suggestion: str = ""


@dataclass
class LibrarySuggestion:
    """A suggestion to extract functions into a shared library."""
    module_name: str
    description: str
    functions: List[Dict[str, Any]]
    unified_api: str        # suggested function signature
    rationale: str


class Severity:
    """Severity levels for issues."""
    CRITICAL = "critical"   # 🔴
    WARNING  = "warning"    # 🟡
    INFO     = "info"       # 🟢

    _ICONS_UNICODE = {
        "critical": "\U0001F534",  # 🔴
        "warning":  "\U0001F7E1",  # 🟡
        "info":     "\U0001F7E2",  # 🟢
    }
    _ICONS_ASCII = {
        "critical": "[!!]",
        "warning":  "[!]",
        "info":     "[i]",
    }

    @staticmethod
    def icon(level: str) -> str:
        from .utils import UNICODE_OK
        icons = Severity._ICONS_UNICODE if UNICODE_OK else Severity._ICONS_ASCII
        return icons.get(level, "?")

