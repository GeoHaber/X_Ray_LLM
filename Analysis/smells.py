
from typing import List, Dict, Any
import asyncio
from collections import Counter

from Core.types import FunctionRecord, ClassRecord, SmellIssue, Severity
from Core.config import SMELL_THRESHOLDS
from Core.inference import LLMHelper
from Core.utils import logger

_BOOL_PREFIXES = ("is_", "has_", "can_", "should_", "check_",
                  "validate_", "contains_", "exists_")


def _check_boolean_blindness(func: FunctionRecord, smells: list):
    """Flag functions returning bool whose name doesn't indicate a question."""
    if (func.return_type and 'bool' in func.return_type.lower()
            and not any(func.name.startswith(p) for p in _BOOL_PREFIXES)):
        smells.append(SmellIssue(
            file_path=func.file_path, line=func.line_start,
            end_line=func.line_end, category="boolean-blindness",
            severity=Severity.INFO, name=func.name,
            metric_value=0,
            message=f"Function '{func.name}' returns bool but name doesn't indicate a question",
            suggestion="Rename to is_/has_/can_/should_/check_ prefix for clarity.",
        ))


async def _enrich_smell_async(smell: SmellIssue, llm: LLMHelper,
                              sem: asyncio.Semaphore):
    """Enrich a single smell with LLM analysis (used by async enrichment)."""
    async with sem:
        prompt = (
            f"Analyze this code smell: {smell.category} in {smell.name}.\n"
            f"Message: {smell.message}\n"
            f"Suggest a specific refactoring (2 sentences max)."
        )
        try:
            suggestion = await llm.completion_async(prompt)
            smell.llm_analysis = suggestion.strip()
        except Exception as e:
            logger.debug(f"Async LLM enrichment failed: {e}")


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

    def detect(self, functions: List[FunctionRecord],
               classes: List[ClassRecord]) -> List[SmellIssue]:
        """Run all heuristic smell detectors. Returns sorted list of SmellIssues."""
        self.smells = []
        for func in functions:
            self._check_function(func)
        for cls in classes:
            self._check_class(cls)
        # Sort: critical first, then by file/line
        self.smells.sort(key=lambda s: (
            0 if s.severity == Severity.CRITICAL else
            1 if s.severity == Severity.WARNING else 2,
            s.file_path, s.line
        ))
        return self.smells
    
    # Legacy alias for backward compatibility with tests
    check = detect

    def _check_function(self, func: FunctionRecord):
        """Dispatch all per-function smell checks."""
        t = self.thresholds
        self._check_long_function(func, t)
        self._check_deep_nesting(func, t)
        self._check_high_complexity(func, t)
        self._check_too_many_params(func, t)
        self._check_missing_docstring(func, t)
        self._check_too_many_returns(func, t)
        _check_boolean_blindness(func, self.smells)
        self._check_too_many_branches(func, t)

    # -- individual smell checks -------------------------------------------

    def _check_long_function(self, func: FunctionRecord, t: dict):
        """Flag functions exceeding the line-count threshold."""
        if func.size_lines >= t["very_long_function"]:
            self.smells.append(SmellIssue(
                file_path=func.file_path, line=func.line_start,
                end_line=func.line_end, category="long-function",
                severity=Severity.CRITICAL, name=func.name,
                metric_value=func.size_lines,
                message=f"Function '{func.name}' is {func.size_lines} lines (limit: {t['very_long_function']})",
                suggestion="Split into smaller focused functions. Extract logical blocks.",
            ))
        elif func.size_lines >= t["long_function"]:
            self.smells.append(SmellIssue(
                file_path=func.file_path, line=func.line_start,
                end_line=func.line_end, category="long-function",
                severity=Severity.WARNING, name=func.name,
                metric_value=func.size_lines,
                message=f"Function '{func.name}' is {func.size_lines} lines (limit: {t['long_function']})",
                suggestion="Consider splitting into smaller functions.",
            ))

    def _check_deep_nesting(self, func: FunctionRecord, t: dict):
        """Flag functions with excessive nesting depth."""
        if func.nesting_depth >= t["very_deep_nesting"]:
            self.smells.append(SmellIssue(
                file_path=func.file_path, line=func.line_start,
                end_line=func.line_end, category="deep-nesting",
                severity=Severity.CRITICAL, name=func.name,
                metric_value=func.nesting_depth,
                message=f"Function '{func.name}' has nesting depth {func.nesting_depth} (limit: {t['very_deep_nesting']})",
                suggestion="Use early returns, guard clauses, or extract nested blocks.",
            ))
        elif func.nesting_depth >= t["deep_nesting"]:
            self.smells.append(SmellIssue(
                file_path=func.file_path, line=func.line_start,
                end_line=func.line_end, category="deep-nesting",
                severity=Severity.WARNING, name=func.name,
                metric_value=func.nesting_depth,
                message=f"Function '{func.name}' has nesting depth {func.nesting_depth} (limit: {t['deep_nesting']})",
                suggestion="Flatten with early returns or extract helper functions.",
            ))

    def _check_high_complexity(self, func: FunctionRecord, t: dict):
        """Flag functions with high cyclomatic complexity."""
        if func.complexity >= t["very_high_complexity"]:
            self.smells.append(SmellIssue(
                file_path=func.file_path, line=func.line_start,
                end_line=func.line_end, category="complex-function",
                severity=Severity.CRITICAL, name=func.name,
                metric_value=func.complexity,
                message=f"Function '{func.name}' has cyclomatic complexity {func.complexity} (limit: {t['very_high_complexity']})",
                suggestion="Decompose into smaller, single-responsibility functions.",
            ))
        elif func.complexity >= t["high_complexity"]:
            self.smells.append(SmellIssue(
                file_path=func.file_path, line=func.line_start,
                end_line=func.line_end, category="complex-function",
                severity=Severity.WARNING, name=func.name,
                metric_value=func.complexity,
                message=f"Function '{func.name}' has cyclomatic complexity {func.complexity} (limit: {t['high_complexity']})",
                suggestion="Simplify branching logic. Consider lookup tables or strategy pattern.",
            ))

    def _check_too_many_params(self, func: FunctionRecord, t: dict):
        """Flag functions with too many parameters."""
        if len(func.parameters) >= t["too_many_params"]:
            self.smells.append(SmellIssue(
                file_path=func.file_path, line=func.line_start,
                end_line=func.line_end, category="too-many-params",
                severity=Severity.WARNING, name=func.name,
                metric_value=len(func.parameters),
                message=f"Function '{func.name}' has {len(func.parameters)} parameters (limit: {t['too_many_params']})",
                suggestion="Group related parameters into a dataclass or config object.",
            ))

    def _check_missing_docstring(self, func: FunctionRecord, t: dict):
        """Flag non-trivial public functions without docstrings."""
        if (not func.docstring
                and func.size_lines >= t["missing_docstring_size"]
                and not func.name.startswith("_")):
            self.smells.append(SmellIssue(
                file_path=func.file_path, line=func.line_start,
                end_line=func.line_end, category="missing-docstring",
                severity=Severity.INFO, name=func.name,
                metric_value=func.size_lines,
                message=f"Function '{func.name}' ({func.size_lines} lines) has no docstring",
                suggestion="Add a docstring explaining purpose, parameters, and return value.",
            ))

    def _check_too_many_returns(self, func: FunctionRecord, t: dict):
        """Flag functions with excessive return statements."""
        if func.return_count >= t["too_many_returns"]:
            self.smells.append(SmellIssue(
                file_path=func.file_path, line=func.line_start,
                end_line=func.line_end, category="too-many-returns",
                severity=Severity.WARNING, name=func.name,
                metric_value=func.return_count,
                message=f"Function '{func.name}' has {func.return_count} return statements (limit: {t['too_many_returns']})",
                suggestion="Consolidate exit points. Consider a result variable.",
            ))

    def _check_too_many_branches(self, func: FunctionRecord, t: dict):
        """Flag functions with excessive branch logic."""
        if func.branch_count >= t["too_many_branches"]:
            self.smells.append(SmellIssue(
                file_path=func.file_path, line=func.line_start,
                end_line=func.line_end, category="too-many-branches",
                severity=Severity.WARNING, name=func.name,
                metric_value=func.branch_count,
                message=f"Function '{func.name}' has {func.branch_count} branches (limit: {t['too_many_branches']})",
                suggestion="Simplify with lookup tables, strategy pattern, or early returns.",
            ))

    def _check_class(self, cls: ClassRecord):
        t = self.thresholds

        # God class (too many methods)
        if cls.method_count >= t["god_class"]:
            self.smells.append(SmellIssue(
                file_path=cls.file_path, line=cls.line_start,
                end_line=cls.line_end, category="god-class",
                severity=Severity.CRITICAL, name=cls.name,
                metric_value=cls.method_count,
                message=f"Class '{cls.name}' has {cls.method_count} methods (limit: {t['god_class']})",
                suggestion="Split into smaller classes with single responsibility."
                           " Consider delegation or mixins.",
            ))

        # Large class (too many lines)
        if cls.size_lines >= t["large_class"]:
            self.smells.append(SmellIssue(
                file_path=cls.file_path, line=cls.line_start,
                end_line=cls.line_end, category="large-class",
                severity=Severity.WARNING, name=cls.name,
                metric_value=cls.size_lines,
                message=f"Class '{cls.name}' is {cls.size_lines} lines (limit: {t['large_class']})",
                suggestion="Extract logical groups of methods into separate classes or modules.",
            ))

        # Missing docstring on class
        if not cls.docstring and cls.size_lines > 30:
            self.smells.append(SmellIssue(
                file_path=cls.file_path, line=cls.line_start,
                end_line=cls.line_end, category="missing-class-docstring",
                severity=Severity.INFO, name=cls.name,
                metric_value=cls.size_lines,
                message=f"Class '{cls.name}' ({cls.size_lines} lines) has no docstring",
                suggestion="Add a docstring explaining the class's responsibility.",
            ))

        # Data class candidate — class with only __init__ setting attributes
        if (cls.method_count <= 3 and cls.has_init
                and not cls.base_classes):
            self.smells.append(SmellIssue(
                file_path=cls.file_path, line=cls.line_start,
                end_line=cls.line_end, category="dataclass-candidate",
                severity=Severity.INFO, name=cls.name,
                metric_value=cls.method_count,
                message=f"Class '{cls.name}' has only {cls.method_count} methods — consider @dataclass",
                suggestion="If this class mainly holds data, convert to @dataclass for less boilerplate.",
            ))

    def enrich_with_llm(self, llm: LLMHelper, max_calls: int = 20):
        """Send the worst smells to LLM for detailed analysis."""
        critical_smells = [
            s for s in self.smells
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
            candidates.extend([s for s in self.smells if s.severity == Severity.WARNING])
        
        candidates = candidates[:15] # Strict limit
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
