"""
Analysis/ai_code_detector.py — AI-Generated Code Pattern Detector (v8.0)
=========================================================================

Detects code patterns statistically associated with AI-generated code
(LLM coding assistants). These patterns are not bugs per se, but signal
"AI Debt" — code that works but may have subtle quality issues:

  * Over-documented: every single line or trivial function has a docstring
  * Excessive abstraction-for-abstraction's sake
  * GPT-style naming conventions (``process_data``, ``handle_request``, etc.)
  * Boilerplate try/except wrapping everything
  * Functions that do exactly ONE thing: call another function

Inspired by the emerging 2025–2026 practice of auditing AI-generated code
for "AI Technical Debt" (arXiv Dec 2025, Reddit r/programming 2026).

Usage::

    from Analysis.ai_code_detector import AICodeDetector

    detector = AICodeDetector()
    report = detector.scan_directory(Path("/my/project"))
    print(f"AI-debt score: {report.ai_debt_score:.1f}")
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

# Naming patterns that heavily correlate with AI-generated names
_GPT_NAME_PATTERNS = re.compile(
    r"^(process|handle|manage|perform|execute|run|do|get|set|create|build|make|"
    r"validate|check|parse|fetch|update|delete|calculate|compute|generate|"
    r"initialize|setup|configure|load|save|send|receive)_\w+$",
    re.IGNORECASE,
)

_SKIP_DIRS = frozenset(
    {"__pycache__", ".git", ".venv", "venv", "node_modules", "tests", "_OLD"}
)


@dataclass
class AIDebtItem:
    """A single AI-generated code pattern finding."""

    file: str
    line: int
    pattern: str  # Pattern name (e.g. "over_documented")
    description: str  # Human-readable description
    severity: str = "info"  # info / warning


@dataclass
class AICodeReport:
    """Aggregate result of AI code detection scan."""

    items: List[AIDebtItem] = field(default_factory=list)
    files_scanned: int = 0

    @property
    def total_findings(self) -> int:
        return len(self.items)

    @property
    def ai_debt_score(self) -> float:
        """
        Score 0–100 where 0 = no AI patterns detected.
        Caps at 100. Warning items count 2×.
        """
        w = sum(2 if i.severity == "warning" else 1 for i in self.items)
        return min(round(w / max(self.files_scanned, 1) * 10, 1), 100.0)

    @property
    def by_pattern(self) -> dict[str, list[AIDebtItem]]:
        cats: dict[str, list[AIDebtItem]] = {}
        for item in self.items:
            cats.setdefault(item.pattern, []).append(item)
        return cats

    def as_dict(self) -> dict:
        return {
            "files_scanned": self.files_scanned,
            "total_findings": len(self.items),
            "ai_debt_score": self.ai_debt_score,
            "by_pattern": {k: len(v) for k, v in self.by_pattern.items()},
            "items": [
                {
                    "file": i.file,
                    "line": i.line,
                    "pattern": i.pattern,
                    "description": i.description,
                    "severity": i.severity,
                }
                for i in self.items[:100]  # cap output
            ],
        }


class AICodeDetector:
    """Detect AI-generated code patterns in Python source files."""

    def __init__(self, extensions: tuple[str, ...] = (".py",)):
        self.extensions = extensions

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan_directory(self, root: Path) -> AICodeReport:
        """Scan all Python files under *root* and return an AICodeReport."""
        report = AICodeReport()
        for path in self._walk(root):
            self._scan_file(path, root, report)
        return report

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _walk(self, root: Path):
        for path in root.rglob("*"):
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            if path.suffix in self.extensions and path.is_file():
                yield path

    def _scan_file(self, path: Path, root: Path, report: AICodeReport) -> None:
        report.files_scanned += 1
        rel = str(path.relative_to(root)).replace("\\", "/")
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            return

        lines = source.splitlines()
        self._check_over_documented(tree, rel, report)
        self._check_gpt_naming(tree, rel, report)
        self._check_wrapper_functions(tree, rel, report)
        self._check_blanket_except(tree, rel, report)
        self._check_docstring_ratio(tree, rel, lines, report)

    # ── Pattern detectors ─────────────────────────────────────────────

    def _check_over_documented(
        self, tree: ast.AST, file: str, report: AICodeReport
    ) -> None:
        """Flag trivial functions (1–3 body stmts) that have docstrings."""
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = node.body
            has_docstring = (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            )
            # Trivial: docstring + ≤2 other statements
            if has_docstring and len(body) <= 3:
                # Check name is also GPT-style → elevate to warning
                severity = "warning" if _GPT_NAME_PATTERNS.match(node.name) else "info"
                report.items.append(
                    AIDebtItem(
                        file=file,
                        line=node.lineno,
                        pattern="over_documented",
                        description=(
                            f"Trivial function '{node.name}' has a docstring "
                            f"but only {len(body) - 1} statement(s) — possible AI boilerplate"
                        ),
                        severity=severity,
                    )
                )

    def _check_gpt_naming(self, tree: ast.AST, file: str, report: AICodeReport) -> None:
        """Flag functions/classes with names matching common AI naming patterns."""
        seen: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            name = node.name
            if name in seen or name.startswith("_"):
                continue
            if _GPT_NAME_PATTERNS.match(name):
                seen.add(name)
                report.items.append(
                    AIDebtItem(
                        file=file,
                        line=node.lineno,
                        pattern="gpt_naming",
                        description=(
                            f"Function '{name}' matches a common AI-generated naming "
                            f"pattern (generic verb_noun convention)"
                        ),
                        severity="info",
                    )
                )

    def _check_wrapper_functions(
        self, tree: ast.AST, file: str, report: AICodeReport
    ) -> None:
        """Flag functions that do nothing but call one other function."""
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = [
                s
                for s in node.body
                if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
            ]  # skip docstring
            if len(body) == 1 and isinstance(body[0], (ast.Return, ast.Expr)):
                stmt = body[0]
                is_single_call = isinstance(getattr(stmt, "value", None), ast.Call)
                if is_single_call:
                    report.items.append(
                        AIDebtItem(
                            file=file,
                            line=node.lineno,
                            pattern="wrapper_function",
                            description=(
                                f"Function '{node.name}' is a single-call wrapper — "
                                f"may be unnecessary indirection added by AI"
                            ),
                            severity="info",
                        )
                    )

    def _check_blanket_except(
        self, tree: ast.AST, file: str, report: AICodeReport
    ) -> None:
        """Flag bare ``except Exception:`` or ``except:`` that swallow errors."""
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            # Bare except or except Exception
            if node.type is None or (
                isinstance(node.type, ast.Name) and node.type.id == "Exception"
            ):
                # Check it's not just re-raising
                body_nodes = [n for n in node.body if not isinstance(n, ast.Raise)]
                if body_nodes:  # has non-raise statements in the except
                    report.items.append(
                        AIDebtItem(
                            file=file,
                            line=node.lineno,
                            pattern="blanket_except",
                            description=(
                                "Bare 'except Exception' or 'except:' that swallows errors — "
                                "common AI-generated error handling pattern"
                            ),
                            severity="warning",
                        )
                    )

    def _check_docstring_ratio(
        self,
        tree: ast.AST,
        file: str,
        lines: list[str],
        report: AICodeReport,
    ) -> None:
        """Flag files where >40% of non-empty lines are docstring/comment content."""
        total = len([ln for ln in lines if ln.strip()])
        if total < 20:
            return  # skip tiny files

        comment_lines = len([ln for ln in lines if ln.strip().startswith("#")])
        docstring_lines = sum(
            1
            for ln in lines
            if ln.strip().startswith('"""') or ln.strip().startswith("'''")
        )
        comment_ratio = (comment_lines + docstring_lines) / total

        if comment_ratio > 0.40:
            report.items.append(
                AIDebtItem(
                    file=file,
                    line=1,
                    pattern="high_comment_ratio",
                    description=(
                        f"File has {comment_ratio:.0%} comment/docstring density "
                        f"(>{40}%%) — possible AI over-documentation"
                    ),
                    severity="info",
                )
            )
