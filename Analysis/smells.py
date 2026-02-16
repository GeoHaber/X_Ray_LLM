
from typing import List, Dict, Any
from Core.types import FunctionRecord, ClassRecord, SmellIssue, Severity
from Core.config import SMELL_THRESHOLDS
from Core.inference import LLMHelper
from Core.utils import logger, UNICODE_OK

class CodeSmellDetector:
    """Detects code smells based on thresholds."""
    
    def __init__(self):
        self.smells: List[SmellIssue] = []
        self.thresholds = SMELL_THRESHOLDS

    def check(self, functions: List[FunctionRecord], classes: List[ClassRecord]):
        """Run checks on all functions and classes."""
        self.smells = []
        for func in functions:
            self._check_function(func)
        for cls in classes:
            self._check_class(cls)

    def _check_function(self, func: FunctionRecord):
        t = self.thresholds

        # Long function
        if func.size_lines >= t["long_function"]:
            sev = Severity.CRITICAL if func.size_lines >= t["very_long_function"] else Severity.WARNING
            self.smells.append(SmellIssue(
                file_path=func.file_path, line=func.line_start,
                end_line=func.line_end, category="long-function",
                severity=sev, name=func.name,
                metric_value=func.size_lines,
                message=f"Function '{func.name}' is {func.size_lines} lines long (limit: {t['long_function']})",
                suggestion="Extract helper functions to reduce size.",
            ))

        # Deep nesting
        if func.nesting_depth >= t["deep_nesting"]:
            sev = Severity.CRITICAL if func.nesting_depth >= t["very_deep_nesting"] else Severity.WARNING
            self.smells.append(SmellIssue(
                file_path=func.file_path, line=func.line_start,
                end_line=func.line_end, category="deep-nesting",
                severity=sev, name=func.name,
                metric_value=func.nesting_depth,
                message=f"Function '{func.name}' has nesting depth {func.nesting_depth} (limit: {t['deep_nesting']})",
                suggestion="Flatten logic using early returns or extract nested blocks.",
            ))

        # High complexity
        if func.complexity >= t["high_complexity"]:
            sev = Severity.CRITICAL if func.complexity >= t["very_high_complexity"] else Severity.WARNING
            self.smells.append(SmellIssue(
                file_path=func.file_path, line=func.line_start,
                end_line=func.line_end, category="complex-function",
                severity=sev, name=func.name,
                metric_value=func.complexity,
                message=f"Function '{func.name}' has cyclomatic complexity {func.complexity} (limit: {t['high_complexity']})",
                suggestion="Simplify logic, reduce branches, or split function.",
            ))

        # Too many parameters
        if len(func.parameters) >= t["too_many_params"]:
            self.smells.append(SmellIssue(
                file_path=func.file_path, line=func.line_start,
                end_line=func.line_end, category="too-many-params",
                severity=Severity.WARNING, name=func.name,
                metric_value=len(func.parameters),
                message=f"Function '{func.name}' has {len(func.parameters)} parameters (limit: {t['too_many_params']})",
                suggestion="Group related parameters into a dataclass or config object.",
            ))

    def _check_class(self, cls: ClassRecord):
        t = self.thresholds

        # God class
        if cls.method_count >= t["god_class"]:
            self.smells.append(SmellIssue(
                file_path=cls.file_path, line=cls.line_start,
                end_line=cls.line_end, category="god-class",
                severity=Severity.CRITICAL, name=cls.name,
                metric_value=cls.method_count,
                message=f"Class '{cls.name}' has {cls.method_count} methods (limit: {t['god_class']})",
                suggestion="Split into smaller classes with single responsibility.",
            ))

        # Large class
        if cls.size_lines >= t["large_class"]:
            self.smells.append(SmellIssue(
                file_path=cls.file_path, line=cls.line_start,
                end_line=cls.line_end, category="large-class",
                severity=Severity.WARNING, name=cls.name,
                metric_value=cls.size_lines,
                message=f"Class '{cls.name}' is {cls.size_lines} lines (limit: {t['large_class']})",
                suggestion="Extract logical groups of methods into separate classes.",
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
                f"Checking code smell:\n"
                f"Issue: {smell.message}\n"
                f"Category: {smell.category}\n"
                f"File: {smell.file_path}:{smell.line}\n\n"
                f"Give a 1-sentence fix recommendation."
            )
            try:
                response = llm.query_sync(prompt, max_tokens=100)
                smell.llm_analysis = response.strip()
            except Exception as e:
                logger.debug(f"LLM enrichment failed: {e}")
