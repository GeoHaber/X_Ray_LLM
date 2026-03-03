import re

import ast
from typing import List, Dict, Any
import asyncio
from collections import Counter

from Core.types import FunctionRecord, ClassRecord, SmellIssue, Severity
from Core.config import SMELL_THRESHOLDS
from Core.inference import LLMHelper, _llm_enrich_one
from Core.utils import logger

_BOOL_PREFIXES = (
    "is_",
    "has_",
    "can_",
    "should_",
    "check_",
    "validate_",
    "contains_",
    "exists_",
)

# Reddit/r/Python: Classes named Common, Utility, Utils, Helper often become god-class dumping grounds
_UTILITY_CLASS_PATTERNS = ("common", "utility", "utils", "helper", "misc", "general")
# Numeric literals that are never flagged as magic numbers
_ALLOWED_MAGIC = frozenset({0, 1, -1, 2, 100})


def _check_magic_numbers(func: FunctionRecord, smells: list, threshold: int = 2):
    """Flag bare numeric literals (other than 0/1/-1/2/100) used in arithmetic/comparisons."""
    try:
        tree = ast.parse(func.code)
    except Exception:
        return
    found = []
    for node in ast.walk(tree):
        # Only flag constants inside binary ops, comparisons, augmented assigns — not in function signatures
        if not isinstance(node, ast.Constant):
            continue
        if not isinstance(node.value, (int, float)):
            continue
        if isinstance(node.value, bool):
            continue
        if node.value in _ALLOWED_MAGIC:
            continue
        found.append(node.value)
    if len(found) >= threshold:
        # de-duplicate for display
        unique = sorted({v for v in found}, key=lambda v: abs(v))[:5]
        sample = ", ".join(str(v) for v in unique)
        smells.append(SmellIssue(
            file_path=func.file_path, line=func.line_start,
            end_line=func.line_end, category="magic-number",
            severity=Severity.INFO, name=func.name,
            metric_value=len(found),
            message=f"Function '{func.name}' contains {len(found)} magic number(s): {sample}",
            suggestion="Extract magic numbers into named constants (e.g. MAX_RETRIES = 5).",
        ))


def _check_mutable_default_arg(func: FunctionRecord, smells: list):
    """Flag functions with mutable default arguments (list, dict, set literals)."""
    try:
        tree = ast.parse(func.code)
    except Exception:
        return
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for default in node.args.defaults + node.args.kw_defaults:
            if default is None:
                continue
            if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                type_name = type(default).__name__.lower().replace('ast.', '')
                smells.append(SmellIssue(
                    file_path=func.file_path, line=func.line_start,
                    end_line=func.line_end, category="mutable-default-arg",
                    severity=Severity.WARNING, name=func.name,
                    metric_value=0,
                    message=f"Function '{func.name}' uses a mutable {type(default).__name__.lower()} as a default argument",
                    suggestion="Use None as default and initialise inside the function body: `if arg is None: arg = []`.",
                ))
                break  # one warning per function is enough
        break  # only check the outermost function def


def _check_dead_code(func: FunctionRecord, smells: list):
    """Flag unreachable statements after an unconditional return/raise."""
    try:
        tree = ast.parse(func.code)
    except Exception:
        return
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.If, ast.For, ast.While, ast.With,
                                  ast.Try)):
            continue
        body = getattr(node, "body", [])
        _scan_body_for_dead_code(body, func, smells)
        # also scan else / orelse branches
        for attr in ("orelse", "finalbody", "handlers"):
            branch = getattr(node, attr, [])
            if isinstance(branch, list):
                _scan_body_for_dead_code(branch, func, smells)


def _scan_body_for_dead_code(body: list, func: FunctionRecord, smells: list):
    """Scan one statement list for unreachable code after return/raise/continue/break."""
    for i, stmt in enumerate(body):
        if isinstance(stmt, (ast.Return, ast.Raise, ast.Continue, ast.Break)):
            remaining = [s for s in body[i + 1:]
                         if not isinstance(s, (ast.Pass, ast.Expr))  # skip bare pass/docstrings
                         or (isinstance(s, ast.Expr) and not isinstance(s.value, ast.Constant))]
            if remaining:
                dead_line = getattr(remaining[0], "lineno", func.line_start)
                stmt_type = type(stmt).__name__.lower()
                smells.append(SmellIssue(
                    file_path=func.file_path,
                    line=dead_line,
                    end_line=getattr(remaining[-1], "end_lineno", dead_line),
                    category="dead-code",
                    severity=Severity.WARNING, name=func.name,
                    metric_value=len(remaining),
                    message=(f"Function '{func.name}' has {len(remaining)} unreachable "
                             f"statement(s) after `{stmt_type}` (line {stmt.lineno})"),
                    suggestion="Remove unreachable code, or move it before the exit statement.",
                ))
                break  # one warning per block per function


# Reddit/r/Python: 99%+ of cases need __init__ only; __new__ adds overhead unless for singletons/immutables
_MIN_METHODS_UTILITY_SMELL = 5


# PEP 8: bare except catches SystemExit/KeyboardInterrupt, masks bugs
_BARE_EXCEPT = re.compile(r"\bexcept\s*:")


def _has_bare_except(code: str) -> bool:
    """PEP 8: avoid bare except clause (no exception type)."""
    return _BARE_EXCEPT.search(code) is not None


def _has_nested_comprehension(code: str) -> bool:
    """Detect nested list/dict comprehensions (Reddit: prefer explicit loops)."""
    for line in code.splitlines():
        stripped = line.strip()
        # ] for = nested list comp; } for = nested dict comp
        if "] for " in stripped or "} for " in stripped:
            return True
    return False


def _check_boolean_blindness(func: FunctionRecord, smells: list):
    """Flag functions returning bool whose name doesn't indicate a question."""
    if (
        func.return_type
        and "bool" in func.return_type.lower()
        and not any(func.name.startswith(p) for p in _BOOL_PREFIXES)
    ):
        smells.append(
            SmellIssue(
                file_path=func.file_path,
                line=func.line_start,
                end_line=func.line_end,
                category="boolean-blindness",
                severity=Severity.INFO,
                name=func.name,
                metric_value=0,
                message=f"Function '{func.name}' returns bool but name doesn't indicate a question",
                suggestion="Rename to is_/has_/can_/should_/check_ prefix for clarity.",
            )
        )


def _check_function_size(func: FunctionRecord, t: dict, smells: list):
    if func.size_lines >= t["very_long_function"]:
        smells.append(
            SmellIssue(
                file_path=func.file_path,
                line=func.line_start,
                end_line=func.line_end,
                category="long-function",
                severity=Severity.CRITICAL,
                name=func.name,
                metric_value=func.size_lines,
                message=f"Function '{func.name}' is {func.size_lines} lines (limit: {t['very_long_function']})",
                suggestion="Split into smaller focused functions. Extract logical blocks.",
            )
        )
    elif func.size_lines >= t["long_function"]:
        smells.append(
            SmellIssue(
                file_path=func.file_path,
                line=func.line_start,
                end_line=func.line_end,
                category="long-function",
                severity=Severity.WARNING,
                name=func.name,
                metric_value=func.size_lines,
                message=f"Function '{func.name}' is {func.size_lines} lines (limit: {t['long_function']})",
                suggestion="Consider splitting into smaller functions.",
            )
        )

def _check_function_complexity(func: FunctionRecord, t: dict, smells: list):
    if func.nesting_depth >= t["very_deep_nesting"]:
        smells.append(
            SmellIssue(
                file_path=func.file_path,
                line=func.line_start,
                end_line=func.line_end,
                category="deep-nesting",
                severity=Severity.CRITICAL,
                name=func.name,
                metric_value=func.nesting_depth,
                message=f"Function '{func.name}' has nesting depth {func.nesting_depth} (limit: {t['very_deep_nesting']})",
                suggestion="Use early returns, guard clauses, or extract nested blocks.",
            )
        )
    elif func.nesting_depth >= t["deep_nesting"]:
        smells.append(
            SmellIssue(
                file_path=func.file_path,
                line=func.line_start,
                end_line=func.line_end,
                category="deep-nesting",
                severity=Severity.WARNING,
                name=func.name,
                metric_value=func.nesting_depth,
                message=f"Function '{func.name}' has nesting depth {func.nesting_depth} (limit: {t['deep_nesting']})",
                suggestion="Flatten with early returns or extract helper functions.",
            )
        )
    if func.complexity >= t["very_high_complexity"]:
        smells.append(
            SmellIssue(
                file_path=func.file_path,
                line=func.line_start,
                end_line=func.line_end,
                category="complex-function",
                severity=Severity.CRITICAL,
                name=func.name,
                metric_value=func.complexity,
                message=f"Function '{func.name}' has cyclomatic complexity {func.complexity} (limit: {t['very_high_complexity']})",
                suggestion="Decompose into smaller, single-responsibility functions.",
            )
        )
    elif func.complexity >= t["high_complexity"]:
        smells.append(
            SmellIssue(
                file_path=func.file_path,
                line=func.line_start,
                end_line=func.line_end,
                category="complex-function",
                severity=Severity.WARNING,
                name=func.name,
                metric_value=func.complexity,
                message=f"Function '{func.name}' has cyclomatic complexity {func.complexity} (limit: {t['high_complexity']})",
                suggestion="Simplify branching logic. Consider lookup tables or strategy pattern.",
            )
        )
    if func.branch_count >= t["too_many_branches"]:
        smells.append(
            SmellIssue(
                file_path=func.file_path,
                line=func.line_start,
                end_line=func.line_end,
                category="too-many-branches",
                severity=Severity.WARNING,
                name=func.name,
                metric_value=func.branch_count,
                message=f"Function '{func.name}' has {func.branch_count} branches (limit: {t['too_many_branches']})",
                suggestion="Simplify with lookup tables, strategy pattern, or early returns.",
            )
        )

def _check_function_signature(func: FunctionRecord, t: dict, smells: list):
    if len(func.parameters) >= t["too_many_params"]:
        smells.append(
            SmellIssue(
                file_path=func.file_path,
                line=func.line_start,
                end_line=func.line_end,
                category="too-many-params",
                severity=Severity.WARNING,
                name=func.name,
                metric_value=len(func.parameters),
                message=f"Function '{func.name}' has {len(func.parameters)} parameters (limit: {t['too_many_params']})",
                suggestion="Group related parameters into a dataclass or config object.",
            )
        )
    if func.return_count >= t["too_many_returns"]:
        smells.append(
            SmellIssue(
                file_path=func.file_path,
                line=func.line_start,
                end_line=func.line_end,
                category="too-many-returns",
                severity=Severity.WARNING,
                name=func.name,
                metric_value=func.return_count,
                message=f"Function '{func.name}' has {func.return_count} return statements (limit: {t['too_many_returns']})",
                suggestion="Consolidate exit points. Consider a result variable.",
            )
        )
    params = getattr(func, "mutable_default_params", None) or []
    if params:
        smells.append(
            SmellIssue(
                file_path=func.file_path,
                line=func.line_start,
                end_line=func.line_end,
                category="mutable-default-arg",
                severity=Severity.WARNING,
                name=func.name,
                metric_value=len(params),
                message=f"Function '{func.name}' uses mutable default for: {', '.join(params)}",
                suggestion="Use None as default, then assign inside: if x is None: x = []",
            )
        )

def _check_function_style(func: FunctionRecord, t: dict, smells: list):
    if (
        not func.docstring
        and func.size_lines >= t["missing_docstring_size"]
        and not func.name.startswith("_")
    ):
        smells.append(
            SmellIssue(
                file_path=func.file_path,
                line=func.line_start,
                end_line=func.line_end,
                category="missing-docstring",
                severity=Severity.INFO,
                name=func.name,
                metric_value=func.size_lines,
                message=f"Function '{func.name}' ({func.size_lines} lines) has no docstring",
                suggestion="Add a docstring explaining purpose, parameters, and return value.",
            )
        )
    _check_boolean_blindness(func, smells)
    if _has_nested_comprehension(func.code):
        smells.append(
            SmellIssue(
                file_path=func.file_path,
                line=func.line_start,
                end_line=func.line_end,
                category="complex-comprehension",
                severity=Severity.INFO,
                name=func.name,
                metric_value=0,
                message=f"Function '{func.name}' contains nested comprehension(s)",
                suggestion="Prefer explicit loops when comprehensions reduce readability.",
            )
        )
    if _has_bare_except(func.code):
        smells.append(
            SmellIssue(
                file_path=func.file_path,
                line=func.line_start,
                end_line=func.line_end,
                category="bare-except",
                severity=Severity.WARNING,
                name=func.name,
                metric_value=0,
                message=f"Function '{func.name}' uses bare except clause",
                suggestion="Catch specific exceptions. Use except Exception if you must catch all errors.",
            )
        )

def _run_function_checks(func: FunctionRecord, t: dict, smells: list):
    """Run all per-function smell checks (extracted to reduce CodeSmellDetector size)."""
    _check_function_size(func, t, smells)
    _check_function_complexity(func, t, smells)
    _check_function_signature(func, t, smells)
    _check_function_style(func, t, smells)


def _run_class_checks(cls, t: dict, smells: list):
    """Run all per-class smell checks (extracted to reduce CodeSmellDetector size)."""
    if cls.method_count >= t["god_class"]:
        smells.append(
            SmellIssue(
                file_path=cls.file_path,
                line=cls.line_start,
                end_line=cls.line_end,
                category="god-class",
                severity=Severity.CRITICAL,
                name=cls.name,
                metric_value=cls.method_count,
                message=f"Class '{cls.name}' has {cls.method_count} methods (limit: {t['god_class']})",
                suggestion="Split into smaller classes with single responsibility. Consider delegation or mixins.",
            )
        )
    if cls.size_lines >= t["large_class"]:
        smells.append(
            SmellIssue(
                file_path=cls.file_path,
                line=cls.line_start,
                end_line=cls.line_end,
                category="large-class",
                severity=Severity.WARNING,
                name=cls.name,
                metric_value=cls.size_lines,
                message=f"Class '{cls.name}' is {cls.size_lines} lines (limit: {t['large_class']})",
                suggestion="Extract logical groups of methods into separate classes or modules.",
            )
        )
    if not cls.docstring and cls.size_lines > 30:
        smells.append(
            SmellIssue(
                file_path=cls.file_path,
                line=cls.line_start,
                end_line=cls.line_end,
                category="missing-class-docstring",
                severity=Severity.INFO,
                name=cls.name,
                metric_value=cls.size_lines,
                message=f"Class '{cls.name}' ({cls.size_lines} lines) has no docstring",
                suggestion="Add a docstring explaining the class's responsibility.",
            )
        )
    if cls.method_count <= 3 and cls.has_init and not cls.base_classes:
        smells.append(
            SmellIssue(
                file_path=cls.file_path,
                line=cls.line_start,
                end_line=cls.line_end,
                category="dataclass-candidate",
                severity=Severity.INFO,
                name=cls.name,
                metric_value=cls.method_count,
                message=f"Class '{cls.name}' has only {cls.method_count} methods — consider @dataclass",
                suggestion="If this class mainly holds data, convert to @dataclass for less boilerplate.",
            )
        )
    name_lower = cls.name.lower()
    if (
        any(name_lower == p or name_lower.endswith(p) for p in _UTILITY_CLASS_PATTERNS)
        and cls.method_count >= _MIN_METHODS_UTILITY_SMELL
    ):
        smells.append(
            SmellIssue(
                file_path=cls.file_path,
                line=cls.line_start,
                end_line=cls.line_end,
                category="utility-class-name",
                severity=Severity.INFO,
                name=cls.name,
                metric_value=cls.method_count,
                message=f"Class '{cls.name}' has {cls.method_count} methods — 'Common/Utils/Helper' often become dumping grounds",
                suggestion="Split by responsibility. Consider delegation or dedicated modules.",
            )
        )
    if "__new__" in cls.methods and "__init__" in cls.methods:
        smells.append(
            SmellIssue(
                file_path=cls.file_path,
                line=cls.line_start,
                end_line=cls.line_end,
                category="new-overuse",
                severity=Severity.INFO,
                name=cls.name,
                metric_value=0,
                message=f"Class '{cls.name}' defines both __new__ and __init__",
                suggestion="Use __init__ only unless you need singletons or immutables.",
            )
        )


async def _enrich_smell_async(
    smell: SmellIssue, llm: LLMHelper, sem: asyncio.Semaphore
):
    """Enrich a single smell with LLM analysis (used by async enrichment)."""
    prompt = (
        f"Analyze this code smell: {smell.category} in {smell.name}.\n"
        f"Message: {smell.message}\n"
        f"Suggest a specific refactoring (2 sentences max)."
    )
    await _llm_enrich_one(
        prompt,
        lambda resp: setattr(smell, "llm_analysis", resp),
        llm,
        sem,
    )


class CodeSmellDetector:
    """
    Detects code smells via AST heuristics, optionally enriched by LLM.

    Two-stage approach:
      Stage 1 (fast):  AST metrics → flag suspects based on thresholds
      Stage 2 (slow):  Send suspects to LLM for detailed analysis + fix suggestions
    """

    def __init__(self, thresholds: Dict[str, int] = None):
        self.thresholds = {**SMELL_THRESHOLDS, **(thresholds or {})}
        self.smells: List[SmellIssue] = []

    def detect(
        self, functions: List[FunctionRecord], classes: List[ClassRecord]
    ) -> List[SmellIssue]:
        """Run all heuristic smell detectors. Returns sorted list of SmellIssues."""
        self.smells = []
        t = self.thresholds
        for func in functions:
            _run_function_checks(func, t, self.smells)
        for cls in classes:
            _run_class_checks(cls, t, self.smells)
        
        self.smells.sort(
            key=lambda s: (
                0 if s.severity == Severity.CRITICAL else
                1 if s.severity == Severity.WARNING else 2,
                s.file_path,
                s.line,
            )
        )
        return self.smells

    check = detect  # Legacy alias for tests

    def enrich_with_llm(self, llm: LLMHelper, max_calls: int = 20):
        """Send the worst smells to LLM for detailed analysis."""
        critical_smells = [
            s
            for s in self.smells
            if s.severity in (Severity.CRITICAL, Severity.WARNING)
            and not s.llm_analysis
        ][:max_calls]

        if not critical_smells:
            return

        logger.info(f"Enriching {len(critical_smells)} smells with LLM...")
        for smell in critical_smells:
            prompt = (
                f"You are a Senior Python Architect reviewing code.\n"
                f"Issue: {smell.message}\n"
                f"Category: {smell.category}\n"
                f"File: {smell.file_path}:{smell.line}\n\n"
                f"Give a 2-3 sentence actionable recommendation to fix this. "
                f"Be specific about WHAT to extract or refactor.\n\n"
                f"Recommendation:"
            )
            try:
                # Note: Still sync for now, will start upgrade in next phase
                response = llm.query_sync(prompt, max_tokens=150)
                smell.llm_analysis = response.strip()
            except Exception as e:
                logger.debug(f"LLM enrichment failed: {e}")

    async def enrich_with_llm_async(self, llm: LLMHelper, concurrency: int = 5):
        """
        Async version: process smells in parallel batches.
        """
        # Pick critical smells first
        candidates = [s for s in self.smells if s.severity == Severity.CRITICAL]
        # Then warnings if space
        if len(candidates) < 10:
            candidates.extend(
                [s for s in self.smells if s.severity == Severity.WARNING]
            )

        candidates = candidates[:15]  # Strict limit
        if not candidates:
            return

        sem = asyncio.Semaphore(concurrency)

        logger.info(f"Enriching {len(candidates)} smells with AI (Async)...")
        tasks = [_enrich_smell_async(smell, llm, sem) for smell in candidates]
        await asyncio.gather(*tasks)

    def summary(self) -> Dict[str, Any]:
        """Return a summary dict of all smells."""
        by_severity = Counter(s.severity for s in self.smells)
        by_category = Counter(s.category for s in self.smells)
        by_file = Counter(s.file_path for s in self.smells)
        return {
            "total": len(self.smells),
            "critical": by_severity.get(Severity.CRITICAL, 0),
            "warning": by_severity.get(Severity.WARNING, 0),
            "info": by_severity.get(Severity.INFO, 0),
            "by_category": dict(by_category),
            "worst_files": dict(by_file.most_common(10)),
        }
