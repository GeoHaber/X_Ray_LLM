"""
X-Ray Multi-Model Pipeline — Orchestrates multiple analysis stages
including pattern scanning, AST validation, taint tracking, and
LLM-based classification / taint-spec inference.

Usage::

    from xray.pipeline import ModelPipeline, PipelineConfig

    cfg = PipelineConfig(llm_backend="openai", max_llm_calls=20)
    pipeline = ModelPipeline(cfg)
    result = pipeline.run("/path/to/project")
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from xray.llm import LLMBackend, create_backend
from xray.scanner import Finding, ScanResult, scan_directory, scan_file

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# Stage names
# ═══════════════════════════════════════════════════════════════════════════

STAGE_PATTERN_SCAN = "pattern_scan"
STAGE_AST_VALIDATION = "ast_validation"
STAGE_TAINT_ANALYSIS = "taint_analysis"
STAGE_LLM_CLASSIFICATION = "llm_classification"
STAGE_LLM_TAINT_INFERENCE = "llm_taint_inference"
STAGE_AUTO_FIX = "auto_fix"
STAGE_TRANSPILE = "transpile"

ALL_STAGES: list[str] = [
    STAGE_PATTERN_SCAN,
    STAGE_AST_VALIDATION,
    STAGE_TAINT_ANALYSIS,
    STAGE_LLM_CLASSIFICATION,
    STAGE_LLM_TAINT_INFERENCE,
    STAGE_AUTO_FIX,
    STAGE_TRANSPILE,
]

# Stages that require an LLM backend to be available.
_LLM_STAGES: set[str] = {STAGE_LLM_CLASSIFICATION, STAGE_LLM_TAINT_INFERENCE, STAGE_TRANSPILE}


# ═══════════════════════════════════════════════════════════════════════════
# Dataclasses
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class TaintSpec:
    """LLM-inferred taint specification for a single file."""

    sources: list[str] = field(default_factory=list)
    sinks: list[str] = field(default_factory=list)
    sanitizers: list[str] = field(default_factory=list)

    def merge(self, other: TaintSpec) -> TaintSpec:
        """Return a new TaintSpec combining self and *other*, deduplicating."""
        return TaintSpec(
            sources=sorted(set(self.sources + other.sources)),
            sinks=sorted(set(self.sinks + other.sinks)),
            sanitizers=sorted(set(self.sanitizers + other.sanitizers)),
        )

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "sources": self.sources,
            "sinks": self.sinks,
            "sanitizers": self.sanitizers,
        }

    @staticmethod
    def from_dict(d: dict) -> TaintSpec:
        return TaintSpec(
            sources=d.get("sources", []),
            sinks=d.get("sinks", []),
            sanitizers=d.get("sanitizers", []),
        )


@dataclass
class PipelineConfig:
    """Configuration for the multi-model analysis pipeline."""

    stages: list[str] = field(default_factory=lambda: list(ALL_STAGES))
    llm_backend: str = "auto"
    max_llm_calls: int = 50
    parallel: bool = False
    confidence_threshold: float = 0.3
    # Forwarded to scan_directory / scan_file
    policy_profile: str = "balanced"
    taint_mode: str = "lite"
    include_tests: bool = False
    # LLM classification tuning
    classify_severities: list[str] = field(
        default_factory=lambda: ["HIGH", "CRITICAL"]
    )
    batch_size: int = 10


@dataclass
class PipelineResult:
    """Aggregated output from a pipeline run."""

    findings: list[Finding] = field(default_factory=list)
    stages_run: list[str] = field(default_factory=list)
    llm_calls_made: int = 0
    taint_specs: dict[str, TaintSpec] = field(default_factory=dict)
    elapsed_ms: float = 0.0

    @property
    def active_findings(self) -> list[Finding]:
        """Findings not suppressed by LLM classification."""
        return [f for f in self.findings if not f.llm_suppressed]

    @property
    def suppressed_findings(self) -> list[Finding]:
        """Findings the LLM classified as false positives."""
        return [f for f in self.findings if f.llm_suppressed]

    def summary(self) -> dict:
        active = self.active_findings
        return {
            "total_findings": len(self.findings),
            "active_findings": len(active),
            "suppressed_findings": len(self.suppressed_findings),
            "stages_run": self.stages_run,
            "llm_calls_made": self.llm_calls_made,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "taint_specs_inferred": len(self.taint_specs),
            "by_severity": {
                sev: sum(1 for f in active if f.severity == sev)
                for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
            },
        }


# ═══════════════════════════════════════════════════════════════════════════
# Prompt templates
# ═══════════════════════════════════════════════════════════════════════════

_CLASSIFY_PROMPT = """\
You are a security code-review expert. For each finding below, decide
whether it is a TRUE_POSITIVE (real issue) or FALSE_POSITIVE (benign match).

Respond with a JSON array.  Each element must have exactly these keys:
  "index"  : int   — the 0-based index in the list below
  "verdict": str   — "TRUE_POSITIVE" or "FALSE_POSITIVE"
  "reason" : str   — one-sentence justification

Findings:
{findings_json}

Respond ONLY with the JSON array, no markdown fences.
"""

_TAINT_SPEC_PROMPT = """\
You are a security analyst. Examine the Python source code below and
identify custom taint sources, sinks, and sanitizers.

Definitions:
- Source: a function/method that returns data controlled by external users
  (e.g., reading from HTTP request, database, file, environment variable).
- Sink: a function/method that is dangerous when called with tainted
  (user-controlled) data (e.g., SQL execution, shell commands, HTML rendering).
- Sanitizer: a function/method that validates or escapes tainted data,
  making it safe for a particular sink.

Respond with a JSON object:
{{
  "sources": ["fully.qualified.name", ...],
  "sinks": ["fully.qualified.name", ...],
  "sanitizers": ["fully.qualified.name", ...]
}}

If a category has no entries, use an empty list.
Respond ONLY with the JSON object, no markdown fences.

Source code ({filepath}):
```python
{code}
```
"""


# ═══════════════════════════════════════════════════════════════════════════
# Helper: robust JSON extraction from LLM output
# ═══════════════════════════════════════════════════════════════════════════

def _extract_json(text: str) -> object:
    """Try to parse JSON from LLM output, stripping markdown fences if present."""
    text = text.strip()
    # Strip ```json ... ``` fences
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


# ═══════════════════════════════════════════════════════════════════════════
# Context extraction helper
# ═══════════════════════════════════════════════════════════════════════════

def _get_code_snippet(filepath: str, line: int, context: int = 5) -> str:
    """Read a few lines around *line* from *filepath*."""
    try:
        path = Path(filepath)
        if not path.is_file():
            return ""
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(0, line - context - 1)
        end = min(len(lines), line + context)
        numbered = [
            f"{i + 1:>4} | {lines[i]}" for i in range(start, end)
        ]
        return "\n".join(numbered)
    except Exception:
        return ""


# ═══════════════════════════════════════════════════════════════════════════
# ModelPipeline
# ═══════════════════════════════════════════════════════════════════════════

class ModelPipeline:
    """Orchestrates a multi-stage code analysis pipeline.

    Stages 1-3 (pattern scan, AST validation, taint analysis) run without
    an LLM backend.  Stages 4-5 (LLM classification, LLM taint inference)
    require a working :class:`LLMBackend`.

    Example::

        pipeline = ModelPipeline(PipelineConfig(llm_backend="openai"))
        result = pipeline.run("/path/to/project")
        for f in result.active_findings:
            print(f)
    """

    def __init__(self, config: PipelineConfig | None = None) -> None:
        self.config: PipelineConfig = config or PipelineConfig()
        self._backend: LLMBackend | None = None
        self._llm_calls: int = 0
        self._taint_spec_cache: dict[str, TaintSpec] = {}

    # ── LLM backend (lazy) ─────────────────────────────────────────────

    def _get_backend(self) -> LLMBackend:
        """Lazily create and return the LLM backend."""
        if self._backend is None:
            self._backend = create_backend(self.config.llm_backend)
        return self._backend

    def _has_llm_budget(self) -> bool:
        return self._llm_calls < self.config.max_llm_calls

    def _llm_generate(self, prompt: str, max_tokens: int = 2048) -> str:
        """Call the LLM backend and track the call count."""
        if not self._has_llm_budget():
            log.warning(
                "LLM call budget exhausted (%d/%d)",
                self._llm_calls,
                self.config.max_llm_calls,
            )
            raise BudgetExhaustedError(
                f"LLM call budget exhausted: {self._llm_calls}/{self.config.max_llm_calls}"
            )
        self._llm_calls += 1
        return self._get_backend().generate(prompt, max_tokens=max_tokens)

    # ── Stage 1-3: scanner (pattern + AST + taint) ─────────────────────

    def _run_scan(
        self,
        target: str,
    ) -> list[Finding]:
        """Run stages 1-3 via the existing scanner infrastructure.

        The scanner already combines pattern matching, AST validation, and
        intra-procedural taint analysis in a single pass, controlled by the
        ``policy_profile`` and ``taint_mode`` configuration knobs.
        """
        path = Path(target)
        if path.is_file():
            findings = scan_file(
                str(path),
                policy_profile=self.config.policy_profile,
                taint_mode=self.config.taint_mode,
                include_tests=self.config.include_tests,
            )
        elif path.is_dir():
            scan_result: ScanResult = scan_directory(
                str(path),
                policy_profile=self.config.policy_profile,
                taint_mode=self.config.taint_mode,
                include_tests=self.config.include_tests,
            )
            findings = scan_result.findings
        else:
            log.error("Target does not exist: %s", target)
            return []

        log.info(
            "Scan complete: %d findings from %s", len(findings), target
        )
        return findings

    # ── Stage 4: LLM classification ────────────────────────────────────

    def classify_findings(self, findings: list[Finding]) -> list[Finding]:
        """Use the LLM to classify findings as TRUE/FALSE positive.

        Only findings whose severity is in ``config.classify_severities``
        are sent to the LLM.  Findings are grouped by ``rule_id`` and sent
        in batches to minimise API calls.

        Returns the same list with ``llm_verdict``, ``llm_reason``, and
        ``llm_suppressed`` updated in-place.
        """
        backend = self._get_backend()
        if not backend.is_available:
            log.warning("LLM backend unavailable; skipping classification")
            return findings

        # Collect indices of findings to classify
        classify_indices: list[int] = [
            i
            for i, f in enumerate(findings)
            if f.severity.upper() in {s.upper() for s in self.config.classify_severities}
        ]

        if not classify_indices:
            log.info("No findings match classify_severities; skipping LLM classification")
            return findings

        # Group by rule_id for batching efficiency
        rule_groups: dict[str, list[int]] = defaultdict(list)
        for idx in classify_indices:
            rule_groups[findings[idx].rule_id].append(idx)

        # Build batches (each batch contains up to batch_size findings)
        batches: list[list[int]] = []
        current_batch: list[int] = []
        for indices in rule_groups.values():
            for idx in indices:
                current_batch.append(idx)
                if len(current_batch) >= self.config.batch_size:
                    batches.append(current_batch)
                    current_batch = []
        if current_batch:
            batches.append(current_batch)

        log.info(
            "LLM classification: %d findings in %d batches",
            len(classify_indices),
            len(batches),
        )

        if self.config.parallel:
            self._classify_parallel(findings, batches)
        else:
            self._classify_sequential(findings, batches)

        return findings

    def _classify_sequential(
        self,
        findings: list[Finding],
        batches: list[list[int]],
    ) -> None:
        for batch in batches:
            if not self._has_llm_budget():
                log.warning("LLM budget exhausted during classification")
                break
            self._classify_batch(findings, batch)

    def _classify_parallel(
        self,
        findings: list[Finding],
        batches: list[list[int]],
    ) -> None:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {}
            for batch in batches:
                if not self._has_llm_budget():
                    break
                future = pool.submit(self._classify_batch, findings, batch)
                futures[future] = batch

            for future in as_completed(futures):
                try:
                    future.result()
                except BudgetExhaustedError:
                    log.warning("LLM budget exhausted during parallel classification")
                except Exception:
                    log.exception("Error in classification batch")

    def _classify_batch(
        self,
        findings: list[Finding],
        batch_indices: list[int],
    ) -> None:
        """Send one batch of findings to the LLM for classification."""
        batch_data = []
        for local_idx, global_idx in enumerate(batch_indices):
            f = findings[global_idx]
            snippet = _get_code_snippet(f.file, f.line)
            batch_data.append(
                {
                    "index": local_idx,
                    "rule_id": f.rule_id,
                    "severity": f.severity,
                    "description": f.description,
                    "file": f.file,
                    "line": f.line,
                    "matched_text": f.matched_text[:200],
                    "code_snippet": snippet,
                }
            )

        prompt = _CLASSIFY_PROMPT.format(
            findings_json=json.dumps(batch_data, indent=2)
        )

        try:
            raw = self._llm_generate(prompt)
            verdicts = _extract_json(raw)
        except BudgetExhaustedError:
            raise
        except Exception:
            log.exception("Failed to parse LLM classification response")
            return

        if not isinstance(verdicts, list):
            log.error("LLM classification returned non-list: %s", type(verdicts))
            return

        for entry in verdicts:
            if not isinstance(entry, dict):
                continue
            local_idx = entry.get("index")
            if local_idx is None or not (0 <= local_idx < len(batch_indices)):
                continue
            global_idx = batch_indices[local_idx]
            verdict = str(entry.get("verdict", "")).upper()
            reason = str(entry.get("reason", ""))

            if verdict in ("TRUE_POSITIVE", "FALSE_POSITIVE"):
                findings[global_idx].llm_verdict = verdict
                findings[global_idx].llm_reason = reason
                findings[global_idx].llm_suppressed = verdict == "FALSE_POSITIVE"
                findings[global_idx].signal_path = "pattern+llm"
                log.debug(
                    "Finding %s:%d classified as %s — %s",
                    findings[global_idx].file,
                    findings[global_idx].line,
                    verdict,
                    reason,
                )

    # ── Stage 5: LLM taint spec inference ──────────────────────────────

    def infer_taint_specs(self, findings: list[Finding]) -> dict[str, TaintSpec]:
        """Ask the LLM to identify custom taint sources/sinks/sanitizers.

        Processes each unique Python file referenced in *findings*.  Results
        are cached per-file so repeated calls are cheap.

        Returns a mapping of filepath -> TaintSpec.
        """
        backend = self._get_backend()
        if not backend.is_available:
            log.warning("LLM backend unavailable; skipping taint inference")
            return {}

        # Collect unique Python files from findings
        py_files: set[str] = set()
        for f in findings:
            if f.file.endswith(".py") and Path(f.file).is_file():
                py_files.add(f.file)

        if not py_files:
            log.info("No Python files in findings; skipping taint inference")
            return {}

        # Filter to files not yet cached
        to_process = [fp for fp in py_files if fp not in self._taint_spec_cache]

        log.info(
            "LLM taint inference: %d files (%d cached, %d to process)",
            len(py_files),
            len(py_files) - len(to_process),
            len(to_process),
        )

        if self.config.parallel and len(to_process) > 1:
            self._infer_taint_parallel(to_process)
        else:
            self._infer_taint_sequential(to_process)

        # Return specs for all requested files (cached + newly inferred)
        return {fp: self._taint_spec_cache[fp] for fp in py_files if fp in self._taint_spec_cache}

    def _infer_taint_sequential(self, filepaths: list[str]) -> None:
        for fp in filepaths:
            if not self._has_llm_budget():
                log.warning("LLM budget exhausted during taint inference")
                break
            self._infer_taint_for_file(fp)

    def _infer_taint_parallel(self, filepaths: list[str]) -> None:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {}
            for fp in filepaths:
                if not self._has_llm_budget():
                    break
                future = pool.submit(self._infer_taint_for_file, fp)
                futures[future] = fp

            for future in as_completed(futures):
                try:
                    future.result()
                except BudgetExhaustedError:
                    log.warning("LLM budget exhausted during parallel taint inference")
                except Exception:
                    log.exception("Error in taint inference for %s", futures[future])

    def _infer_taint_for_file(self, filepath: str) -> None:
        """Infer taint spec for a single file and cache the result."""
        if filepath in self._taint_spec_cache:
            return

        try:
            code = Path(filepath).read_text(encoding="utf-8", errors="replace")
        except Exception:
            log.exception("Failed to read %s for taint inference", filepath)
            return

        # Truncate very large files to avoid blowing the context window
        max_chars = 12_000
        if len(code) > max_chars:
            code = code[:max_chars] + "\n# ... (truncated) ..."

        prompt = _TAINT_SPEC_PROMPT.format(filepath=filepath, code=code)

        try:
            raw = self._llm_generate(prompt, max_tokens=1024)
            data = _extract_json(raw)
        except BudgetExhaustedError:
            raise
        except Exception:
            log.exception("Failed to parse taint spec for %s", filepath)
            return

        if not isinstance(data, dict):
            log.error("LLM taint spec returned non-dict for %s", filepath)
            return

        spec = TaintSpec(
            sources=[str(s) for s in data.get("sources", []) if isinstance(s, str)],
            sinks=[str(s) for s in data.get("sinks", []) if isinstance(s, str)],
            sanitizers=[str(s) for s in data.get("sanitizers", []) if isinstance(s, str)],
        )
        self._taint_spec_cache[filepath] = spec
        log.info(
            "Taint spec for %s: %d sources, %d sinks, %d sanitizers",
            filepath,
            len(spec.sources),
            len(spec.sinks),
            len(spec.sanitizers),
        )

    # ── Confidence filtering ───────────────────────────────────────────

    @staticmethod
    def _filter_by_confidence(
        findings: list[Finding],
        threshold: float,
    ) -> list[Finding]:
        """Remove findings below the confidence threshold."""
        kept = [f for f in findings if f.confidence >= threshold]
        removed = len(findings) - len(kept)
        if removed:
            log.info(
                "Confidence filter: removed %d findings below %.2f threshold",
                removed,
                threshold,
            )
        return kept

    # ── Main entry point ───────────────────────────────────────────────

    def run(self, target: str) -> PipelineResult:
        """Execute the pipeline against *target* (file or directory).

        Runs only the stages listed in ``config.stages``.  Stages 4-5 are
        silently skipped when the LLM backend is unavailable.

        Returns a :class:`PipelineResult`.
        """
        t0 = time.monotonic()
        self._llm_calls = 0
        result = PipelineResult()
        stages = self.config.stages
        findings: list[Finding] = []

        # Validate stage names
        for stage in stages:
            if stage not in ALL_STAGES:
                log.warning("Unknown pipeline stage '%s', skipping", stage)

        # ── Stages 1-3: pattern scan + AST + taint ────────────────────
        # The existing scanner handles all three in one pass.  We map the
        # first three stage names to a single scan invocation.
        scan_stages = {STAGE_PATTERN_SCAN, STAGE_AST_VALIDATION, STAGE_TAINT_ANALYSIS}
        if scan_stages & set(stages):
            findings = self._run_scan(target)
            for s in (STAGE_PATTERN_SCAN, STAGE_AST_VALIDATION, STAGE_TAINT_ANALYSIS):
                if s in stages:
                    result.stages_run.append(s)

        # ── Confidence filter ─────────────────────────────────────────
        findings = self._filter_by_confidence(
            findings, self.config.confidence_threshold
        )

        # ── Stage 4: LLM classification ───────────────────────────────
        if STAGE_LLM_CLASSIFICATION in stages:
            backend = self._get_backend()
            if backend.is_available:
                try:
                    findings = self.classify_findings(findings)
                    result.stages_run.append(STAGE_LLM_CLASSIFICATION)
                except BudgetExhaustedError:
                    log.warning("LLM budget exhausted during classification stage")
                    result.stages_run.append(STAGE_LLM_CLASSIFICATION)
            else:
                log.info(
                    "LLM backend not available; skipping %s",
                    STAGE_LLM_CLASSIFICATION,
                )

        # ── Stage 5: LLM taint spec inference ─────────────────────────
        if STAGE_LLM_TAINT_INFERENCE in stages:
            backend = self._get_backend()
            if backend.is_available:
                try:
                    result.taint_specs = self.infer_taint_specs(findings)
                    result.stages_run.append(STAGE_LLM_TAINT_INFERENCE)
                except BudgetExhaustedError:
                    log.warning("LLM budget exhausted during taint inference stage")
                    result.taint_specs = dict(self._taint_spec_cache)
                    result.stages_run.append(STAGE_LLM_TAINT_INFERENCE)
            else:
                log.info(
                    "LLM backend not available; skipping %s",
                    STAGE_LLM_TAINT_INFERENCE,
                )

        result.findings = findings
        result.llm_calls_made = self._llm_calls
        result.elapsed_ms = (time.monotonic() - t0) * 1000
        log.info(
            "Pipeline complete: %d findings (%d active, %d suppressed) in %.1f ms, %d LLM calls",
            len(result.findings),
            len(result.active_findings),
            len(result.suppressed_findings),
            result.elapsed_ms,
            result.llm_calls_made,
        )
        return result

    def run_without_llm(self, target: str) -> PipelineResult:
        """Convenience: run only stages 1-3 (no LLM required)."""
        original_stages = self.config.stages
        self.config.stages = [
            STAGE_PATTERN_SCAN,
            STAGE_AST_VALIDATION,
            STAGE_TAINT_ANALYSIS,
        ]
        try:
            return self.run(target)
        finally:
            self.config.stages = original_stages


# ═══════════════════════════════════════════════════════════════════════════
# Exceptions
# ═══════════════════════════════════════════════════════════════════════════

class BudgetExhaustedError(RuntimeError):
    """Raised when the LLM call budget is exceeded."""
