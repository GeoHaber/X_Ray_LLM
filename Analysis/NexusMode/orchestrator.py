"""
Analysis.NexusMode.orchestrator
===============================

The Nexus Orchestrator is a decoupled pipeline that identifies structural bottlenecks
in Python code, translates them to Rust via pluggable adapters, and verifies the
result using highly concurrent Cargo validation.
"""

import ast
import asyncio
import logging
import tempfile
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Any

from Analysis.NexusMode.adapters import (
    BaseTranspilerAdapter,
    XRayTranspilerAdapter,
    DepylerAdapter,
    PyrsAdapter,
)

logger = logging.getLogger("Nexus_Orchestrator")


# ── Data Structures ──────────────────────────────────────────────────────────


@dataclass
class TargetNode:
    """Represents a specific Python AST node identified for transpilation."""

    file_path: Path
    function_name: str
    ast_node: ast.FunctionDef


@dataclass
class TranslationResult:
    """Result of passing a TargetNode through a transpiler adapter."""

    node: TargetNode
    adapter_name: str
    rust_code: str = ""
    success: bool = False
    error_msg: str = ""


@dataclass
class VerifiedResult:
    """Result of verifying translated Rust code via Cargo."""

    translation: TranslationResult
    compiled_successfully: bool = False
    cargo_stderr: str = ""


# ── Stage 1: Analyzer ────────────────────────────────────────────────────────


class Analyzer:
    """Scans Python files to extract structural bottlenecks (FunctionDefs)."""

    @staticmethod
    def identify_targets(files: List[Path], progress_cb=None) -> List[TargetNode]:
        logger.info(f"Analyzer: Scanning {len(files)} files for bottlenecks...")
        targets = []
        total = len(files)

        for i, file_path in enumerate(files):
            if not file_path.exists():
                continue
            try:
                code = file_path.read_text(encoding="utf-8")
                tree = ast.parse(code)
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        # Bottleneck heuristic: >10 lines or contains loops
                        if len(node.body) > 10 or any(
                            isinstance(stmt, (ast.For, ast.While)) for stmt in node.body
                        ):
                            targets.append(
                                TargetNode(
                                    file_path=file_path,
                                    function_name=node.name,
                                    ast_node=node,
                                )
                            )
            except Exception as e:
                logger.debug(f"Analyzer failed parsing {file_path.name}: {e}")

            if progress_cb:
                progress_cb(i + 1, total)

        logger.info(f"Analyzer: Found {len(targets)} structural bottlenecks.")
        return targets


# ── Stage 2: TranslatorBridge ────────────────────────────────────────────────


class TranslatorBridge:
    """Routes AST Nodes through pluggable transpiler adapters."""

    def __init__(self):
        self.adapters: Dict[str, BaseTranspilerAdapter] = {
            "x-ray": XRayTranspilerAdapter(),
            "depyler": DepylerAdapter(),
            "pyrs": PyrsAdapter(),
        }

    def translate(
        self, targets: List[TargetNode], target_adapter: str = "x-ray", progress_cb=None
    ) -> List[TranslationResult]:
        if target_adapter not in self.adapters:
            raise ValueError(
                f"Unknown adapter '{target_adapter}'. Valid options: {list(self.adapters.keys())}"
            )

        adapter = self.adapters[target_adapter]
        logger.info(
            f"TranslatorBridge: Routing {len(targets)} targets through '{target_adapter}'..."
        )

        results = []
        total = len(targets)

        for i, target in enumerate(targets):
            res = TranslationResult(node=target, adapter_name=target_adapter)
            try:
                rust_code = adapter.transpile(target.ast_node, context=target.file_path)
                res.rust_code = rust_code
                res.success = True
            except Exception as e:
                logger.warning(
                    f"TranslatorBridge failed to transpile {target.function_name}: {e}"
                )
                res.error_msg = str(e)

            results.append(res)
            if progress_cb:
                progress_cb(i + 1, total)

        return results


# ── Stage 3: CargoVerifier ───────────────────────────────────────────────────


class CargoVerifier:
    """Uses asynchronous subprocesses to rapidly verify generated Rust code."""

    @staticmethod
    async def _verify_single(translation: TranslationResult) -> VerifiedResult:
        res = VerifiedResult(translation=translation)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            # 1. Init Cargo lib
            init_proc = await asyncio.create_subprocess_exec(
                "cargo",
                "init",
                "--lib",
                "--name",
                "nexus_verification",
                cwd=tmp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await init_proc.communicate()

            # 2. Write wrapped code
            code = translation.rust_code
            lib_rs = tmp_path / "src" / "lib.rs"
            wrapped_code = f"// Verified by Nexus CargoVerifier\n{code}\n"
            lib_rs.write_text(wrapped_code, encoding="utf-8")

            # 3. Cargo Check
            check_proc = await asyncio.create_subprocess_exec(
                "cargo",
                "check",
                cwd=tmp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await check_proc.communicate()

            if check_proc.returncode == 0:
                res.compiled_successfully = True
                logger.info(
                    f"[PASS] {translation.node.function_name} compiled successfully in Rust."
                )
            else:
                res.cargo_stderr = stderr.decode("utf-8", errors="replace")
                logger.warning(
                    f"[FAIL] {translation.node.function_name} failed cargo check."
                )

        return res

    @staticmethod
    async def verify_all_async(
        translations: List[TranslationResult], progress_cb=None
    ) -> List[VerifiedResult]:
        successful_translations = [t for t in translations if t.success]
        logger.info(
            f"CargoVerifier: Checking {len(successful_translations)} functions asynchronously..."
        )

        tasks = [CargoVerifier._verify_single(t) for t in successful_translations]
        verified_results = []

        total = len(tasks)
        for i, coro in enumerate(asyncio.as_completed(tasks)):
            result = await coro
            verified_results.append(result)
            if progress_cb:
                progress_cb(i + 1, total)

        return verified_results

    @staticmethod
    def verify_all(
        translations: List[TranslationResult], progress_cb=None
    ) -> List[VerifiedResult]:
        """Synchronous wrapper for the async verification."""
        return asyncio.run(CargoVerifier.verify_all_async(translations, progress_cb))


# ── Nexus Orchestrator (Pipeline Manager) ────────────────────────────────────


class NexusOrchestrator:
    """
    Coordinates the Analyzer, TranslatorBridge, and CargoVerifier pipelines.
    Provides backwards compatibility for existing CLI and UI integrations.
    """

    def __init__(self, target_project_path: Path):
        self.project_path = target_project_path
        self.graph_index: Dict[str, Any] = {"bottlenecks": []}  # Backwards compat
        self._targets: List[TargetNode] = []

    def build_context_graph(self, files: List[Path], progress_cb=None):
        """Phase 1: Analyze code and find bottlenecks."""
        self._targets = Analyzer.identify_targets(files, progress_cb)

        # Mirror back to legacy structure for UI
        self.graph_index["bottlenecks"] = [
            {"file": t.file_path, "function": t.function_name, "node": t.ast_node}
            for t in self._targets
        ]

    def run_transpilation_pipeline(
        self, target_adapter: str = "x-ray", progress_cb=None
    ) -> List[Dict[str, Any]]:
        """Phase 2: Translate targets."""
        bridge = TranslatorBridge()
        translations = bridge.translate(self._targets, target_adapter, progress_cb)

        # Map back to legacy dictionary format expected by `run_nexus_on_transpiler.py`
        results = []
        for t in translations:
            res = {
                "function": t.node.function_name,
                "file": str(t.node.file_path),
                "rust_code": t.rust_code if t.success else "",
                "status": "success" if t.success else "failed",
            }
            if not t.success:
                res["error"] = t.error_msg
            results.append(res)

        return results

    def verify_and_build(
        self, transpilation_results: List[Dict[str, Any]], progress_cb=None
    ) -> List[Dict[str, Any]]:
        """Phase 3: Verify with Cargo asynchronously."""
        # Map legacy dicts back to dataclasses for the Verifier
        translations = []
        for r in transpilation_results:
            # We don't have the original target node here easily without state mapping,
            # but we can reconstruct a stub just for verification reporting.
            if r["status"] == "success":
                stub_node = TargetNode(
                    file_path=Path(r["file"]),
                    function_name=r["function"],
                    ast_node=None,
                )
                translations.append(
                    TranslationResult(
                        node=stub_node,
                        adapter_name="x-ray",
                        rust_code=r["rust_code"],
                        success=True,
                    )
                )

        verified_results = CargoVerifier.verify_all(translations, progress_cb)

        # Re-map legacy format
        output = []
        for v in verified_results:
            if v.compiled_successfully:
                output.append(
                    {
                        "function": v.translation.node.function_name,
                        "file": str(v.translation.node.file_path),
                        "rust_code": v.translation.rust_code,
                        "status": "success",
                    }
                )
            else:
                # Update the original transpilation result dict in-place if tracking errors
                for r in transpilation_results:
                    if r["function"] == v.translation.node.function_name:
                        r["cargo_error"] = v.cargo_stderr

        return output


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    dummy_path = Path(".")
    orchestrator = NexusOrchestrator(dummy_path)
