"""Analysis/release_readiness.py — Pre-release readiness analyzer.

Runs a battery of checks that answer "Is this project safe to ship?":
  1. TODO/FIXME/HACK scanner     — finds release-blocking comments
  2. Docstring coverage          — measures documentation completeness
  3. Dependency vulnerability     — wraps pip-audit for known CVEs
  4. Version consistency          — ensures versions match across files
  5. Dependency pinning           — checks for unpinned requirements
  6. Orphan module detector       — finds unreferenced .py files
"""

from __future__ import annotations

import ast
import re
import logging
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Any, Optional

from Core.types import Severity
from Core.ui_bridge import get_bridge

logger = logging.getLogger("X_RAY_RELEASE")

# ── Marker patterns ────────────────────────────────────────────────────

_MARKER_PATTERNS = [
    ("FIXME", Severity.WARNING, re.compile(r"#\s*FIXME\b", re.IGNORECASE)),
    ("TODO", Severity.INFO, re.compile(r"#\s*TODO\b", re.IGNORECASE)),
    ("HACK", Severity.WARNING, re.compile(r"#\s*HACK\b", re.IGNORECASE)),
    ("XXX", Severity.WARNING, re.compile(r"#\s*XXX\b", re.IGNORECASE)),
    ("NOCOMMIT", Severity.CRITICAL, re.compile(r"#\s*NOCOMMIT\b", re.IGNORECASE)),
    ("TEMP", Severity.INFO, re.compile(r"#\s*TEMP\b", re.IGNORECASE)),
]

# ── Version file patterns ──────────────────────────────────────────────

_VERSION_RE = re.compile(
    r"""(?:__version__|version)\s*=\s*["']([^"']+)["']""", re.IGNORECASE
)
_TOML_VERSION_RE = re.compile(r"""^version\s*=\s*["']([^"']+)["']""", re.MULTILINE)


# ── Dataclasses ────────────────────────────────────────────────────────


@dataclass
class MarkerHit:
    file_path: str
    line: int
    kind: str  # marker kind (e.g. "TODO", "HACK")
    text: str  # the actual comment text
    severity: str


@dataclass
class DocstringGap:
    file_path: str
    name: str  # function/class name
    line: int
    kind: str  # "function" or "class"


@dataclass
class DepVulnerability:
    package: str
    version: str
    vuln_id: str  # CVE or PYSEC id
    description: str
    fix_version: str
    severity: str


@dataclass
class VersionMismatch:
    source: str  # "pyproject.toml", "config.py", etc.
    version: str


@dataclass
class UnpinnedDep:
    file_path: str
    line: int
    package: str
    spec: str  # e.g. ">=2.0" or "" (no version)


@dataclass
class OrphanModule:
    file_path: str  # relative path


@dataclass
class ReleaseReport:
    """Aggregated release readiness results."""

    markers: List[MarkerHit] = field(default_factory=list)
    docstring_gaps: List[DocstringGap] = field(default_factory=list)
    docstring_total: int = 0
    docstring_documented: int = 0
    vulnerabilities: List[DepVulnerability] = field(default_factory=list)
    dep_audit_available: bool = False
    version_sources: List[VersionMismatch] = field(default_factory=list)
    versions_consistent: bool = True
    unpinned_deps: List[UnpinnedDep] = field(default_factory=list)
    orphan_modules: List[OrphanModule] = field(default_factory=list)
    score: float = 100.0
    grade: str = "A+"


# ── Main analyzer ──────────────────────────────────────────────────────


class ReleaseReadinessAnalyzer:
    """Pre-release readiness checker — runs all 6 sub-checks."""

    def __init__(self):
        self.report: Optional[ReleaseReport] = None

    # ── Public API ────────────────────────────────────────────────────

    def analyze(
        self,
        root: Path,
        exclude: Optional[List[str]] = None,
        functions: Optional[list] = None,
        classes: Optional[list] = None,
    ) -> ReleaseReport:
        """Run all release readiness checks on *root*."""
        bridge = get_bridge()
        report = ReleaseReport()

        py_files = self._collect_py_files(root, exclude)

        bridge.status("  Scanning TODO/FIXME/HACK markers...")
        report.markers = self._scan_markers(root, py_files)

        bridge.status("  Measuring docstring coverage...")
        self._check_docstrings(root, py_files, report, functions, classes)

        bridge.status("  Auditing dependency vulnerabilities...")
        self._audit_dependencies(report)

        bridge.status("  Checking version consistency...")
        self._check_versions(root, report)

        bridge.status("  Checking dependency pinning...")
        self._check_pinning(root, report)

        bridge.status("  Detecting orphan modules...")
        self._detect_orphans(root, py_files, report)

        report.score = self._compute_score(report)
        report.grade = self._score_to_letter(report.score)
        self.report = report
        return report

    def summary(self) -> Dict[str, Any]:
        """Return summary dict compatible with collect_reports / grading."""
        r = self.report
        if not r:
            return {}
        # Count severities across markers + vulns + unpinned
        crit = sum(1 for m in r.markers if m.severity == Severity.CRITICAL)
        crit += sum(1 for v in r.vulnerabilities if v.severity == Severity.CRITICAL)
        warn = sum(1 for m in r.markers if m.severity == Severity.WARNING)
        warn += len(r.unpinned_deps)
        warn += 0 if r.versions_consistent else 1
        info = sum(1 for m in r.markers if m.severity == Severity.INFO)
        info += len(r.orphan_modules)
        total = crit + warn + info

        doc_pct = (
            round(r.docstring_documented / r.docstring_total * 100, 1)
            if r.docstring_total
            else 100.0
        )

        return {
            "total": total,
            "critical": crit,
            "warning": warn,
            "info": info,
            "markers": len(r.markers),
            "markers_by_kind": dict(Counter(m.kind for m in r.markers)),
            "docstring_coverage_pct": doc_pct,
            "docstring_total": r.docstring_total,
            "docstring_documented": r.docstring_documented,
            "docstring_gaps": len(r.docstring_gaps),
            "vulnerabilities": len(r.vulnerabilities),
            "dep_audit_available": r.dep_audit_available,
            "versions_consistent": r.versions_consistent,
            "version_sources": [
                {"source": v.source, "version": v.version} for v in r.version_sources
            ],
            "unpinned_deps": len(r.unpinned_deps),
            "orphan_modules": len(r.orphan_modules),
            "score": r.score,
            "grade": r.grade,
        }

    # ── 1. TODO / FIXME / HACK marker scanner ────────────────────────

    def _scan_markers(self, root: Path, py_files: List[Path]) -> List[MarkerHit]:
        hits: List[MarkerHit] = []
        for fpath in py_files:
            try:
                lines = fpath.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            rel = self._rel(root, fpath)
            for lineno, line in enumerate(lines, 1):
                for kind, severity, pattern in _MARKER_PATTERNS:
                    if pattern.search(line):
                        hits.append(
                            MarkerHit(
                                file_path=rel,
                                line=lineno,
                                kind=kind,
                                text=line.strip(),
                                severity=severity,
                            )
                        )
        return hits

    # ── 2. Docstring coverage ────────────────────────────────────────

    @staticmethod
    def _tally_symbol(name, has_doc, file_path, line, kind, gaps):
        """Count one public symbol and record its gap if undocumented."""
        if name.startswith("_"):
            return 0, 0
        if has_doc:
            return 1, 1
        gaps.append(DocstringGap(file_path=file_path, name=name, line=line, kind=kind))
        return 1, 0

    def _docstrings_from_files(self, root, py_files, gaps):
        """Fallback: parse files to count docstrings when AST data is unavailable."""
        total = 0
        documented = 0
        for fpath in py_files:
            try:
                tree = ast.parse(
                    fpath.read_text(encoding="utf-8", errors="ignore"),
                    filename=str(fpath),
                )
            except SyntaxError:
                continue
            rel = self._rel(root, fpath)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    t, d = self._tally_symbol(
                        node.name,
                        ast.get_docstring(node),
                        rel,
                        node.lineno,
                        "function",
                        gaps,
                    )
                elif isinstance(node, ast.ClassDef):
                    t, d = self._tally_symbol(
                        node.name,
                        ast.get_docstring(node),
                        rel,
                        node.lineno,
                        "class",
                        gaps,
                    )
                else:
                    continue
                total += t
                documented += d
        return total, documented

    def _check_docstrings(
        self,
        root: Path,
        py_files: List[Path],
        report: ReleaseReport,
        functions: Optional[list],
        classes: Optional[list],
    ):
        total = 0
        documented = 0
        gaps: List[DocstringGap] = []

        if functions or classes:
            for func in functions or []:
                t, d = self._tally_symbol(
                    func.name,
                    func.docstring,
                    func.file_path,
                    func.line_start,
                    "function",
                    gaps,
                )
                total += t
                documented += d
            for cls in classes or []:
                t, d = self._tally_symbol(
                    cls.name,
                    cls.docstring,
                    cls.file_path,
                    cls.line_start,
                    "class",
                    gaps,
                )
                total += t
                documented += d
        else:
            total, documented = self._docstrings_from_files(root, py_files, gaps)

        report.docstring_total = total
        report.docstring_documented = documented
        report.docstring_gaps = gaps

    # ── 3. Dependency vulnerability audit ────────────────────────────

    def _audit_dependencies(self, report: ReleaseReport):
        try:
            result = subprocess.run(
                ["pip-audit", "--format=json", "--progress-spinner=off"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            report.dep_audit_available = True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            report.dep_audit_available = False
            return

        if result.returncode not in (0, 1):
            report.dep_audit_available = False
            return

        try:
            import json

            data = json.loads(result.stdout)
        except (ValueError, KeyError):
            return

        vulns = data if isinstance(data, list) else data.get("dependencies", [])
        for dep in vulns:
            pkg = dep.get("name", "")
            ver = dep.get("version", "")
            for v in dep.get("vulns", []):
                sev = (
                    Severity.CRITICAL
                    if "critical" in v.get("description", "").lower()
                    else Severity.WARNING
                )
                report.vulnerabilities.append(
                    DepVulnerability(
                        package=pkg,
                        version=ver,
                        vuln_id=v.get("id", ""),
                        description=v.get("description", "")[:200],
                        fix_version=v.get("fix_versions", [""])[0]
                        if v.get("fix_versions")
                        else "",
                        severity=sev,
                    )
                )

    # ── 4. Version consistency ───────────────────────────────────────

    def _check_versions(self, root: Path, report: ReleaseReport):
        sources: List[VersionMismatch] = []

        # Check pyproject.toml
        toml_path = root / "pyproject.toml"
        if toml_path.is_file():
            content = toml_path.read_text(encoding="utf-8", errors="ignore")
            m = _TOML_VERSION_RE.search(content)
            if m:
                sources.append(VersionMismatch("pyproject.toml", m.group(1)))

        # Check setup.py / setup.cfg
        for name in ("setup.py", "setup.cfg"):
            p = root / name
            if p.is_file():
                content = p.read_text(encoding="utf-8", errors="ignore")
                m = _VERSION_RE.search(content)
                if m:
                    sources.append(VersionMismatch(name, m.group(1)))

        # Check common version files
        for pattern in ("**/config.py", "**/version.py", "**/__init__.py"):
            for p in root.glob(pattern):
                # Skip venvs and caches
                parts = p.relative_to(root).parts
                if any(
                    skip in parts
                    for skip in (
                        ".venv",
                        "venv",
                        "node_modules",
                        "__pycache__",
                        ".git",
                        "site-packages",
                    )
                ):
                    continue
                try:
                    content = p.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                m = _VERSION_RE.search(content)
                if m:
                    rel = str(p.relative_to(root)).replace("\\", "/")
                    sources.append(VersionMismatch(rel, m.group(1)))

        report.version_sources = sources
        versions = {s.version for s in sources}
        report.versions_consistent = len(versions) <= 1

    # ── 5. Dependency pinning ────────────────────────────────────────

    def _check_pinning(self, root: Path, report: ReleaseReport):
        req_files = list(root.glob("requirements*.txt"))
        for req_file in req_files:
            try:
                lines = req_file.read_text(
                    encoding="utf-8", errors="ignore"
                ).splitlines()
            except OSError:
                continue
            rel = str(req_file.relative_to(root)).replace("\\", "/")
            for lineno, line in enumerate(lines, 1):
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("-"):
                    continue
                # Parse package name and version spec
                # Formats: pkg==1.0, pkg>=1.0, pkg, pkg~=1.0
                m = re.match(r"^([A-Za-z0-9_.-]+)\s*(.*)", line)
                if not m:
                    continue
                pkg = m.group(1)
                spec = m.group(2).strip()
                if not spec or not spec.startswith("=="):
                    report.unpinned_deps.append(
                        UnpinnedDep(
                            file_path=rel,
                            line=lineno,
                            package=pkg,
                            spec=spec or "(no version)",
                        )
                    )

    # ── 6. Orphan module detector ────────────────────────────────────

    @staticmethod
    def _collect_imported_names(py_files: List[Path]) -> set:
        """Gather all imported module names (and parent packages) from *py_files*."""
        imported: set = set()
        for fpath in py_files:
            try:
                tree = ast.parse(
                    fpath.read_text(encoding="utf-8", errors="ignore"),
                    filename=str(fpath),
                )
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                names: List[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    imported.add(name)
                    parts = name.split(".")
                    for i in range(1, len(parts)):
                        imported.add(".".join(parts[:i]))
        return imported

    _ORPHAN_ENTRY_POINTS = frozenset(
        {
            "x_ray_claude",
            "x_ray_flet",
            "x_ray_exe",
            "x_ray_web",
            "x_ray_desktop",
            "conftest",
            "setup",
            "manage",
        }
    )

    def _detect_orphans(self, root: Path, py_files: List[Path], report: ReleaseReport):
        # Build set of all modules
        all_modules: Dict[str, str] = {}  # module_dotted -> relative path
        for fpath in py_files:
            rel = self._rel(root, fpath)
            mod = rel.replace(".py", "").replace("/", ".").replace("\\", ".")
            if mod.endswith(".__init__"):
                all_modules[mod[: -len(".__init__")]] = rel
            all_modules[mod] = rel

        imported = self._collect_imported_names(py_files)

        for mod, rel in all_modules.items():
            basename = mod.split(".")[-1]
            if basename in ("__init__", "conftest"):
                continue
            if basename in self._ORPHAN_ENTRY_POINTS:
                continue
            if "test" in mod.lower() or "xray_generated" in rel:
                continue
            if "_scratch" in rel or "_training_ground" in rel:
                continue
            # CI scripts and optional extension packages are not imported
            if ".github" in rel or "_rustified" in rel:
                continue
            if mod not in imported:
                report.orphan_modules.append(OrphanModule(file_path=rel))

    # ── Scoring ──────────────────────────────────────────────────────

    def _compute_score(self, r: ReleaseReport) -> float:
        score = 100.0

        # Markers penalty
        for m in r.markers:
            if m.severity == Severity.CRITICAL:
                score -= 3.0
            elif m.severity == Severity.WARNING:
                score -= 0.5
            else:
                score -= 0.1
        score = max(score, 100.0 - 20.0)  # cap marker penalty at 20

        # Docstring coverage penalty (up to 15 pts)
        if r.docstring_total > 0:
            pct = r.docstring_documented / r.docstring_total
            doc_penalty = max(0, (0.5 - pct) * 30)  # penalty kicks in below 50%
            score -= min(doc_penalty, 15.0)

        # Vulnerability penalty (up to 25 pts)
        for v in r.vulnerabilities:
            if v.severity == Severity.CRITICAL:
                score -= 5.0
            else:
                score -= 2.0
        score = max(score, 100.0 - 25.0 - 20.0)  # don't double-cap, use running

        # Version inconsistency penalty
        if not r.versions_consistent:
            score -= 5.0

        # Unpinned deps penalty (up to 10 pts)
        score -= min(len(r.unpinned_deps) * 0.5, 10.0)

        # Orphan modules (small penalty, up to 5 pts)
        score -= min(len(r.orphan_modules) * 0.3, 5.0)

        return round(max(0.0, min(100.0, score)), 1)

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _collect_py_files(
        root: Path, exclude: Optional[List[str]] = None
    ) -> List[Path]:
        skip = {
            ".venv",
            "venv",
            "node_modules",
            "__pycache__",
            ".git",
            "site-packages",
            ".tox",
            ".eggs",
            "dist",
            "build",
        }
        if exclude:
            skip.update(exclude)
        files = []
        for p in root.rglob("*.py"):
            if any(part in skip for part in p.relative_to(root).parts):
                continue
            files.append(p)
        return sorted(files)

    @staticmethod
    def _rel(root: Path, p: Path) -> str:
        try:
            return str(p.relative_to(root)).replace("\\", "/")
        except ValueError:
            return str(p)

    @staticmethod
    def _score_to_letter(score: float) -> str:
        if score >= 97:
            return "A+"
        if score >= 93:
            return "A"
        if score >= 90:
            return "A-"
        if score >= 87:
            return "B+"
        if score >= 83:
            return "B"
        if score >= 80:
            return "B-"
        if score >= 70:
            return "C"
        if score >= 60:
            return "D"
        return "F"


# Module-level convenience stubs (MarkerHit is a dataclass — no singleton)

def analyze(source_code: str, project_root: str = None):
    """Placeholder — use ReleaseReadinessAnalyzer.analyze() directly."""
    raise NotImplementedError("Use ReleaseReadinessAnalyzer.analyze() instead")

def summary(issues=None):
    """Placeholder — use ReleaseReadinessAnalyzer directly."""
    raise NotImplementedError("Use ReleaseReadinessAnalyzer directly")

