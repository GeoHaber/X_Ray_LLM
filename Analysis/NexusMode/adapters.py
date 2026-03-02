"""
Analysis.NexusMode.adapters
===========================

Pluggable Transpiler Interface abstracting multiple AST-to-Rust approaches.
Provides robust native traversing and fully weaponized Subprocess proxying.
"""

import ast
import subprocess  # nosec B404
import tempfile
import logging
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger("Nexus_Adapters")

# Try to import X_Ray's native AST transpiler for fallback
try:
    from Analysis.transpiler import transpile_function_code
except ImportError:
    transpile_function_code = None

class BaseTranspilerAdapter(ABC):
    """
    The Base Transpiler Interface required by the Nexus Orchestrator.
    """
    
    @abstractmethod
    def transpile(self, node: ast.AST, context: Path) -> str:
        """
        Accepts a Python AST node & filepath, returns generated Rust string.
        Should raise ValueError/RuntimeError on failure, avoiding silent fake-okays.
        """
        pass

class XRayTranspilerAdapter(BaseTranspilerAdapter):
    """
    Wraps X-Ray's native AST Transpiler with defensive error handling.
    Catches visitation errors and prevents the entire Orchestrator pipeline from crashing.
    """
    def transpile(self, node: ast.AST, context: Path) -> str:
        if not transpile_function_code:
            raise RuntimeError("X-Ray Native Transpiler module not found or failed to import.")
            
        try:
            # Reconstruct the function source dynamically from the AST node
            function_code = ast.unparse(node)
            return transpile_function_code(code=function_code, name_hint=node.name, source_info=str(context))
        except Exception as e:
            logger.error(f"Native XRay Transpiler crashed on node {getattr(node, 'name', '<unknown>')}: {e}")
            raise RuntimeError(f"Native Transpilation failed: {e}") from e

class SubprocessTranspilerAdapter(BaseTranspilerAdapter):
    """
    Generalized Adapter for invoking CLI-based Rust transpilers.
    Rounds-trips the Python AST node through a temporary `.py` script,
    shells out to a binary, and reads back the resulting text.
    """
    def __init__(self, binary_name: str, args_template: list[str]):
        """
        :param binary_name: e.g., 'pyrs' or 'depyler'
        :param args_template: list of arguments where '{input_file}' will be replaced 
                              with the path to the temporary python file.
        """
        self.binary_name = binary_name
        self.args_template = args_template

    def transpile(self, node: ast.AST, context: Path) -> str:
        try:
            # 1. Re-serialize the specific AST Node back to Python source code.
            # We don't want to transpile the whole file, just this bottleneck.
            source_snippet = ast.unparse(node)
        except Exception as e:
            raise ValueError(f"Failed to unparse AST node for {self.binary_name}: {e}") from e

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            py_file = tmp_path / "snippet.py"
            py_file.write_text(source_snippet, encoding='utf-8')
            
            # Format arguments
            args = [self.binary_name] + [
                arg.format(input_file=str(py_file)) for arg in self.args_template
            ]

            try:
                # 2. Shell out to the target compiler binary
                proc = subprocess.run(  # nosec B603
                    args, 
                    cwd=tmp_path, 
                    capture_output=True, 
                    text=True,
                    check=False  # We manually check the return code
                )
                
                if proc.returncode != 0:
                    raise RuntimeError(f"CLI '{self.binary_name}' failed: {proc.stderr}")
                    
                # 3. Read output (if the CLI outputs to stdout, use proc.stdout. 
                # If it outputs to a file, read the file. Assuming stdout for now).
                output = proc.stdout.strip()
                if not output:
                    raise RuntimeError(f"CLI '{self.binary_name}' produced no output.")
                    
                return output
                
            except FileNotFoundError:
                raise RuntimeError(
                    f"Transpiler binary '{self.binary_name}' not found on PATH. "
                    "Ensure it is installed to use this adapter."
                )

class DepylerAdapter(SubprocessTranspilerAdapter):
    """
    Adapter for `paiml/depyler`.
    Focuses on strict typed boundaries and memory safety verifications.
    """
    def __init__(self):
        # E.g., `depyler compile ./snippet.py`
        super().__init__(binary_name="depyler", args_template=["compile", "{input_file}"])

class PyrsAdapter(SubprocessTranspilerAdapter):
    """
    Adapter for `konchunas/pyrs`.
    Applies broad syntax mappings for raw porting jobs.
    """
    def __init__(self):
        # E.g., `pyrs ./snippet.py`
        super().__init__(binary_name="pyrs", args_template=["{input_file}"])

