
import ast
import hashlib
import builtins as _builtins_mod
import copy
import logging
from pathlib import Path
from typing import List, Tuple, Optional
import os
from Core.types import FunctionRecord, ClassRecord
from Core.config import _ALWAYS_SKIP
from Core.ast_helpers import compute_nesting_depth, compute_complexity

logger = logging.getLogger("X_RAY_AST")

# Built-in names preserved during AST normalisation
_BUILTIN_NAMES = frozenset(dir(_builtins_mod))

# Files containing intentional bad code for testing — skip during scanning
_ALWAYS_SKIP_FILES = frozenset({"smell_factory.py", "bad_code_sample.py"})


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
        node.name = "func"
        if (node.body and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)):
            node.body.pop(0)
        for arg in node.args.args:
            if arg.arg != 'self':
                name = f"arg{self.arg_count}"
                self.arg_map[arg.arg] = name
                arg.arg = name
                self.arg_count += 1
        self.generic_visit(node)
        return node

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Store, ast.Load)):
            if node.id in self.arg_map:
                node.id = self.arg_map[node.id]
            elif node.id in _BUILTIN_NAMES:
                pass  # preserve builtins (print, len, range, etc.)
            elif node.id not in self.var_map:
                name = f"var{self.var_count}"
                self.var_map[node.id] = name
                self.var_count += 1
                node.id = name
            else:
                node.id = self.var_map[node.id]
        return node

    def visit_arg(self, node):
        if node.arg in self.arg_map:
            node.arg = self.arg_map[node.arg]
        return node


def _compute_structure_hash(node: ast.AST) -> str:
    """Compute hash of normalized AST dump for structural fingerprinting."""
    try:
        normalized = ASTNormalizer().visit(copy.deepcopy(node))
        return hashlib.sha256(ast.dump(normalized).encode()).hexdigest()
    except Exception:
        return ""


def _walk_definitions(node: ast.AST):
    """Yield top-level and class-method function/class defs, skipping nested functions."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield child
        elif isinstance(child, ast.ClassDef):
            yield child
            yield from _walk_definitions(child)
        else:
            yield from _walk_definitions(child)


def extract_functions_from_file(fpath: Path, root: Path) -> Tuple[
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

    for node in _walk_definitions(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_record = _build_function_record(node, rel_path, source, lines)
            functions.append(func_record)
        elif isinstance(node, ast.ClassDef):
            class_record = _build_class_record(node, rel_path)
            classes.append(class_record)

    return functions, classes, None


def _build_function_record(node: ast.AST, rel_path: str, source: str,
                          lines: List[str]) -> FunctionRecord:
    """Extract FunctionRecord from AST node (replaces 50-line inline block)."""
    start = max(node.lineno - 1, 0)
    end = node.end_lineno or start + 1
    code = "\n".join(lines[start:end])
    code_hash = hashlib.sha256(code.encode()).hexdigest()
    
    params = [a.arg for a in node.args.args if a.arg != "self"]
    ret = ast.unparse(node.returns) if node.returns and hasattr(ast, "unparse") else None
    
    try:
        decorators = [ast.unparse(d) for d in node.decorator_list]
    except Exception:
        decorators = []

    # Extract function calls
    calls = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            if isinstance(child.func, ast.Name):
                calls.append(child.func.id)
            elif isinstance(child.func, ast.Attribute):
                calls.append(child.func.attr)

    return FunctionRecord(
        name=node.name,
        file_path=rel_path,
        line_start=node.lineno,
        line_end=end,
        size_lines=end - start,
        parameters=params,
        return_type=ret,
        decorators=decorators,
        docstring=ast.get_docstring(node) or None,
        calls_to=list(set(calls)),
        complexity=compute_complexity(node),
        nesting_depth=compute_nesting_depth(node),
        code_hash=code_hash,
        structure_hash=_compute_structure_hash(node),
        code=code,
        return_count=sum(1 for n in ast.walk(node) if isinstance(n, ast.Return)),
        branch_count=sum(1 for n in ast.walk(node) if isinstance(n, ast.If)),
        is_async=isinstance(node, ast.AsyncFunctionDef),
    )


def _build_class_record(node: ast.ClassDef, rel_path: str) -> ClassRecord:
    """Extract ClassRecord from AST node (replaces 30-line inline block)."""
    start = max(node.lineno - 1, 0)
    end = node.end_lineno or start + 1
    
    methods = [n.name for n in ast.walk(node)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    
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


def collect_py_files(root: Path, exclude: List[str] = None,
                     include: List[str] = None) -> List[Path]:
    """Walk root and return .py files respecting include/exclude rules."""
    exclude = exclude or []
    include = include or []
    results = []
    try:
        walker = os.walk(root)
    except PermissionError:
        logger.warning(f"Permission denied: {root}")
        return results
    for dirpath, dirnames, filenames in walker:
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

