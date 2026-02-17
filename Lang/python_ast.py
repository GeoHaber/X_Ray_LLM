
import ast
import hashlib
import os
import concurrent.futures
from pathlib import Path
from typing import List, Tuple, Optional

from Core.types import FunctionRecord, ClassRecord
from Core.ast_helpers import compute_nesting_depth, compute_complexity

# === AST Extraction Engine ===

class ASTNormalizer(ast.NodeTransformer):
    """
    Normalizes AST to detect structural duplicates.
    1. Removes docstrings.
    2. Renames all arguments to 'argN'.
    3. Renames all local variables to 'varN' (simple scope-agnostic).
    """
    def __init__(self):
        self.arg_map = {}
        self.var_map = {}
        self.arg_count = 0
        self.var_count = 0

    def visit_FunctionDef(self, node):
        # Rename function to generic placeholder for comparison
        node.name = "func"

        # Strip docstring
        if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str):
            node.body.pop(0)
        
        # Normalize arguments
        for arg in node.args.args:
            if arg.arg != 'self':
                name = f"arg{self.arg_count}"
                self.arg_map[arg.arg] = name
                arg.arg = name
                self.arg_count += 1
        
        self.generic_visit(node)
        return node

    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Store, ast.Load)):
            if node.id in self.arg_map:
                node.id = self.arg_map[node.id]
            elif node.id not in self.var_map:
                name = f"var{self.var_count}"
                self.var_map[node.id] = name
                self.var_count += 1
                node.id = name
            else:
                node.id = self.var_map[node.id]
        return node

    def visit_arg(self, node):
        # Backup for nested scopes or lambdas
        if node.arg in self.arg_map:
            node.arg = self.arg_map[node.arg]
        return node


def _compute_structure_hash(node: ast.AST) -> str:
    """Compute MD5 of normalized structure."""
    
    # 1. Try Rust Accelerator (Phase 2)
    try:
        if os.getenv("X_RAY_DISABLE_RUST"):
            raise ImportError("Rust disabled by env var")
            
        from Core.utils import verify_rust_environment
        if not verify_rust_environment():
            raise RuntimeError("Environment verification failed")

        from Core import x_ray_core
        # For Rust, we currently accept source string, not AST node.
        # So we unparse the node first, then let Rust strip docstrings/etc.
        # This is a deviation from the pure AST transform but faster for now.
        code = ast.unparse(node)
        normalized = x_ray_core.normalize_code(code)
        return hashlib.sha256(normalized.encode()).hexdigest()
    except (ImportError, AttributeError, Exception):
        # Fallback to Python AST Normalizer
        pass

    try:
        # Deep copy because NodeTransformer modifies in-place
        import copy
        normalized = ASTNormalizer().visit(copy.deepcopy(node))
        # dump() returns a string representation of the tree structure
        return hashlib.sha256(ast.dump(normalized).encode()).hexdigest()
    except Exception:
        return ""

def _extract_calls(node: ast.AST) -> List[str]:
    """Collect unique call target names from a function AST node."""
    calls: List[str] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if isinstance(child.func, ast.Name):
            calls.append(child.func.id)
        elif isinstance(child.func, ast.Attribute):
            calls.append(child.func.attr)
    return list(set(calls))


def _safe_unparse_decorators(decorator_list) -> List[str]:
    """Unparse decorator nodes, returning [] on failure."""
    try:
        return [ast.unparse(d) for d in decorator_list]
    except Exception:
        return []


def _process_function_node(
    node, lines: List[str], rel_path: str,
) -> FunctionRecord:
    """Build a FunctionRecord from a FunctionDef/AsyncFunctionDef node."""
    start = max(node.lineno - 1, 0)
    end = node.end_lineno or start + 1
    code = "\n".join(lines[start:end])
    code_hash = hashlib.sha256(code.encode()).hexdigest()
    structure_hash = _compute_structure_hash(node)

    params = [a.arg for a in node.args.args if a.arg != "self"]
    ret = ast.unparse(node.returns) if node.returns and hasattr(ast, "unparse") else None

    return FunctionRecord(
        name=node.name,
        file_path=rel_path,
        line_start=node.lineno,
        line_end=end,
        size_lines=end - start,
        parameters=params,
        return_type=ret,
        decorators=_safe_unparse_decorators(node.decorator_list),
        docstring=ast.get_docstring(node) or None,
        calls_to=_extract_calls(node),
        complexity=compute_complexity(node),
        nesting_depth=compute_nesting_depth(node),
        code_hash=code_hash,
        structure_hash=structure_hash,
        code=code,
        is_async=isinstance(node, ast.AsyncFunctionDef),
    )


def _process_class_node(
    node: ast.ClassDef, lines: List[str], rel_path: str,
) -> ClassRecord:
    """Build a ClassRecord from a ClassDef node."""
    start = max(node.lineno - 1, 0)
    end = node.end_lineno or start + 1
    methods = [
        n.name for n in ast.walk(node)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    bases = []
    for b in node.bases:
        try:
            bases.append(ast.unparse(b))
        except Exception:
            bases.append("?")

    return ClassRecord(
        name=node.name,
        file_path=rel_path,
        line_start=node.lineno,
        line_end=end,
        size_lines=end - start,
        method_count=len(methods),
        base_classes=bases,
        docstring=ast.get_docstring(node) or None,
        methods=methods,
        has_init="__init__" in methods,
    )


def _extract_functions_from_file(fpath: Path, root: Path) -> Tuple[
        List[FunctionRecord], List[ClassRecord], Optional[str]]:
    """Parse one file and extract all functions and classes."""
    try:
        source = fpath.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return [], [], str(e)

    try:
        tree = ast.parse(source, filename=str(fpath))
    except SyntaxError as e:
        return [], [], f"SyntaxError: {e}"

    rel_path = str(fpath.relative_to(root)).replace("\\", "/")
    lines = source.splitlines()
    functions = []
    classes = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(_process_function_node(node, lines, rel_path))
        elif isinstance(node, ast.ClassDef):
            classes.append(_process_class_node(node, lines, rel_path))

    return functions, classes, None

_ALWAYS_SKIP = frozenset({
    ".git", ".hg", ".svn", "__pycache__", ".mypy_cache", ".pytest_cache",
    ".tox", ".nox", ".eggs", "node_modules",
    "venv", ".venv", "env", ".env",
    "site-packages", "dist-packages",
    "_archive", "_Old", "_old", "_bin",
    "_scratch", ".github",
    "portable", "target",
})

# Files containing intentional bad code for testing — skip during scanning
_ALWAYS_SKIP_FILES = frozenset({"smell_factory.py", "bad_code_sample.py"})


def collect_py_files(root: Path, exclude: List[str] = None,
                     include: List[str] = None) -> List[Path]:
    """Walk root and return .py files respecting include/exclude rules."""
    exclude = exclude or []
    include = include or []
    results = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        # Prune dirs in-place
        dirnames[:] = [
            d for d in dirnames
            if d not in _ALWAYS_SKIP
            and not d.endswith(".egg-info")
            and not (exclude and any(
                (os.path.join(rel_dir, d) if rel_dir != "." else d).startswith(p)
                for p in exclude))
        ]
        if include:
            top = rel_dir.split(os.sep)[0] if rel_dir != "." else "."
            if top != "." and not any(top.startswith(p) for p in include):
                continue
        for fn in filenames:
            if fn.endswith(".py") and fn not in _ALWAYS_SKIP_FILES:
                results.append(Path(dirpath) / fn)
    return results


def scan_codebase(root: Path, exclude: List[str] = None,
                  include: List[str] = None) -> Tuple[
        List[FunctionRecord], List[ClassRecord], List[str]]:
    """Parallel-scan the codebase, returning functions, classes, and errors."""
    py_files = collect_py_files(root, exclude, include)
    all_functions: List[FunctionRecord] = []
    all_classes: List[ClassRecord] = []
    errors: List[str] = []

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(_extract_functions_from_file, f, root): f
            for f in py_files
        }
        for future in concurrent.futures.as_completed(futures):
            funcs, clses, err = future.result()
            all_functions.extend(funcs)
            all_classes.extend(clses)
            if err:
                errors.append(f"{futures[future]}: {err}")

    return all_functions, all_classes, errors
