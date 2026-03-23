"""
Typed dictionaries for X-Ray API and analyzer responses.

Provides static typing for the most common response structures
returned by analyzer functions and API handlers.
"""

from __future__ import annotations

from typing import TypedDict

# ── Browse / File browser ────────────────────────────────────────────────


class FileItem(TypedDict):
    name: str
    path: str
    is_dir: bool
    size: int | None


class BrowseResult(TypedDict, total=False):
    current: str
    parent: str | None
    items: list[FileItem]
    error: str


class DriveInfo(TypedDict):
    name: str
    path: str
    is_dir: bool


# ── Scanner findings ─────────────────────────────────────────────────────


class FindingDict(TypedDict, total=False):
    rule_id: str
    rule_name: str
    severity: str
    file: str
    line: int
    message: str
    suggestion: str
    category: str


class ScanSummary(TypedDict):
    total: int
    high: int
    medium: int
    low: int


class ScanResult(TypedDict, total=False):
    files_scanned: int
    findings: list[FindingDict]
    summary: ScanSummary
    grade: str
    elapsed_ms: float
    error: str


# ── Format / Type checking ───────────────────────────────────────────────


class FormatResult(TypedDict, total=False):
    needs_format: int
    files: list[str]
    all_formatted: bool
    error: str


class TypeDiagnostic(TypedDict, total=False):
    file: str
    location: str
    message: str
    severity: str


class TypeCheckResult(TypedDict, total=False):
    total_diagnostics: int
    errors: int
    warnings: int
    diagnostics: list[TypeDiagnostic]
    clean: bool
    error: str


# ── Project health ───────────────────────────────────────────────────────


class HealthCheck(TypedDict):
    name: str
    status: str
    file: str
    description: str
    severity: str


class HealthResult(TypedDict):
    score: int
    passed: int
    total: int
    checks: list[HealthCheck]


class RemediationEstimate(TypedDict):
    total_minutes: int
    total_hours: float
    per_finding: list[str]


# ── Code smells ──────────────────────────────────────────────────────────


class SmellItem(TypedDict):
    file: str
    line: int
    severity: str
    smell: str
    description: str
    metric: int | float


class SmellResult(TypedDict):
    smells: list[SmellItem]
    total: int
    by_type: dict[str, int]


# ── Dead functions ───────────────────────────────────────────────────────


class DeadFunction(TypedDict):
    name: str
    file: str
    line: int
    lines: int


class DeadFunctionResult(TypedDict):
    dead_functions: list[DeadFunction]
    total_defined: int
    total_dead: int
    total_called: int


# ── Security (Bandit) ───────────────────────────────────────────────────


class BanditIssue(TypedDict, total=False):
    file: str
    line: int
    severity: str
    confidence: str
    rule_id: str
    rule_name: str
    description: str
    cwe: str


class SecretFinding(TypedDict):
    file: str
    line: int
    type: str
    severity: str


class SecurityResult(TypedDict, total=False):
    bandit_issues: list[BanditIssue]
    secrets: list[SecretFinding]
    total_issues: int
    total_secrets: int
    error: str


# ── PM Dashboard ─────────────────────────────────────────────────────────


class RiskFileEntry(TypedDict, total=False):
    file: str
    risk_score: float
    loc: int
    security: float
    quality: float
    smells: float
    churn: float
    duplicates: float


class RiskHeatmapResult(TypedDict):
    files: list[RiskFileEntry]
    total_files: int
    max_risk: float
    high_risk: int
    medium_risk: int
    low_risk: int


# ── Generic API response ────────────────────────────────────────────────


class ErrorResponse(TypedDict):
    error: str


class StatusResponse(TypedDict):
    status: str
