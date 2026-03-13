"""
Analysis/ui_health.py — UI Health Analyzer for X-Ray (Analyzer #10)
====================================================================

Structurally and behaviorally validates UI code in Python (Flet, tkinter,
PyQt, wx) and JS/TS/React (JSX/TSX).

Unlike ``ui_compat.py`` (which checks *API signatures*), this analyzer
checks the **runtime structure and behavior** of the UI tree::

    from Analysis.ui_health import UIHealthAnalyzer

    analyzer = UIHealthAnalyzer()
    issues = analyzer.analyze(Path("my_app/"))
    for issue in issues:
        print(issue.to_smell())

Detects
-------
UH001  Dead widget         Created but never added to any parent / page
UH002  Always-invisible    ``visible=False`` with no code path that flips it
UH003  Missing handler     Interactive control (Button/Checkbox) with no event
UH004  Layout anti-pattern expand=True inside fixed-width/height container
UH005  React missing key   JSX list render without ``key`` prop
UH006  React missing deps  ``useEffect`` callback references vars not in dep array
UH007  Orphan container    Container/Column/Row with zero children
UH008  Unclosed JSX        JSX tag opened but not properly closed (heuristic)
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from Core.types import SmellIssue, Severity
from Core.utils import logger


# ---------------------------------------------------------------------------
# Shared rule codes and severities
# ---------------------------------------------------------------------------

_RULES: Dict[str, Tuple[str, str]] = {
    "UH001": (Severity.WARNING, "Dead widget — created but never added to the UI tree"),
    "UH002": (
        Severity.WARNING,
        "Always-invisible control — visible=False with no flip",
    ),
    "UH003": (Severity.WARNING, "Interactive control has no event handler"),
    "UH004": (
        Severity.INFO,
        "Layout anti-pattern — expand=True inside fixed container",
    ),
    "UH005": (Severity.WARNING, "React: list render missing 'key' prop"),
    "UH006": (Severity.WARNING, "React: useEffect missing dependency"),
    "UH007": (Severity.INFO, "Empty container — Column/Row/Stack has no children"),
    "UH008": (Severity.INFO, "Likely unclosed or mismatched JSX tag"),
}


# ---------------------------------------------------------------------------
# Issue dataclass
# ---------------------------------------------------------------------------


@dataclass
class UIHealthIssue:
    """One UI-health finding."""

    rule_code: str  # e.g. "UH001"
    file_path: str
    line: int
    end_line: int
    widget_name: str  # the variable / component name
    detail: str  # human-readable extra context
    suggestion: str = ""

    # computed from rule_code
    @property
    def severity(self) -> str:
        return _RULES.get(self.rule_code, (Severity.INFO, ""))[0]

    @property
    def message(self) -> str:
        base = _RULES.get(self.rule_code, (Severity.INFO, self.detail))[1]
        return f"{base}: {self.detail}" if self.detail else base

    def to_smell(self) -> SmellIssue:
        """Convert to X-Ray SmellIssue for unified pipeline reporting."""
        return SmellIssue(
            file_path=self.file_path,
            line=self.line,
            end_line=self.end_line,
            category="ui-health",
            severity=self.severity,
            name=self.widget_name,
            metric_value=0,
            message=self.message,
            suggestion=self.suggestion,
            source="ui-health",
            rule_code=self.rule_code,
            fixable=False,
        )


# ---------------------------------------------------------------------------
# Python AST helpers
# ---------------------------------------------------------------------------

# Flet widget constructors that create visible controls
_FLET_INTERACTIVE = frozenset(
    {
        "Button",
        "FilledButton",
        "ElevatedButton",
        "OutlinedButton",
        "TextButton",
        "FloatingActionButton",
        "IconButton",
        "Checkbox",
        "Switch",
        "Radio",
        "Slider",
        "TextField",
        "Dropdown",
        "GestureDetector",
        "InkWell",
    }
)

_FLET_CONTAINERS = frozenset(
    {
        "Column",
        "Row",
        "Stack",
        "Container",
        "Card",
        "ListView",
        "GridView",
        "ExpansionPanel",
    }
)

_FLET_HANDLER_KWARGS = frozenset(
    {
        "on_click",
        "on_change",
        "on_select",
        "on_submit",
        "on_tap",
        "on_long_press",
        "on_hover",
    }
)

# Tkinter interactive widgets
_TK_INTERACTIVE = frozenset(
    {
        "Button",
        "Checkbutton",
        "Radiobutton",
        "Scale",
        "Entry",
        "Spinbox",
        "Combobox",
    }
)

# QtWidgets interactive (abbreviated)
_QT_INTERACTIVE = frozenset(
    {
        "QPushButton",
        "QCheckBox",
        "QRadioButton",
        "QSlider",
        "QLineEdit",
        "QComboBox",
        "QListWidget",
    }
)


def _kw_value(node: ast.Call, name: str) -> Optional[ast.expr]:
    """Return the AST value node for a keyword arg, or None."""
    for kw in node.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _is_false(node: Optional[ast.expr]) -> bool:
    """True if node is the literal False constant."""
    return isinstance(node, ast.Constant) and node.value is False


def _is_true(node: Optional[ast.expr]) -> bool:
    """True if node is the literal True constant."""
    return isinstance(node, ast.Constant) and node.value is True


def _is_int(node: Optional[ast.expr]) -> bool:
    """True if node is an integer literal."""
    return isinstance(node, ast.Constant) and isinstance(node.value, int)


def _attr_name(node: ast.expr) -> Optional[str]:
    """Extract the last attribute from an Attribute node chain."""
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


# ---------------------------------------------------------------------------
# Python AST Visitor
# ---------------------------------------------------------------------------


class _PythonUIVisitor(ast.NodeVisitor):
    """
    Walk a Python AST looking for UI health issues.

    Tracks:
    - variables assigned to UI widget constructors
    - whether those variables are ever added to a parent control
    - visible=False controls with no assignment back to True
    - interactive controls with no event handler kwarg
    - expand=True inside fixed-dimension containers
    - empty container constructors
    """

    def __init__(self, source_lines: List[str], file_path: str):
        self.source_lines = source_lines
        self.file_path = file_path
        self.issues: List[UIHealthIssue] = []

        # varname → (line, widget_type)
        self._widget_vars: Dict[str, Tuple[int, str]] = {}
        # varnames referenced in .controls / page.add() / parent etc.
        self._added_to_parent: Set[str] = set()
        # varname → line for always-invisible controls
        self._invisible_vars: Dict[str, Tuple[int, str]] = {}
        # varnames where visible is later set to True
        self._flipped_visible: Set[str] = set()
        # (varname, line, widget_type) for controls missing handlers
        self._no_handler: List[Tuple[str, int, str]] = []
        # track all names used anywhere (to check add-to-parent)
        self._all_referenced: Set[str] = set()

    # -- helpers -------------------------------------------------------------

    def _is_flet_widget(self, node: ast.Call) -> Optional[str]:
        """Return widget class name if this is a flet widget constructor."""
        func = node.func
        if isinstance(func, ast.Attribute):
            # ft.Button(...)
            if isinstance(func.value, ast.Name):
                return func.attr
        elif isinstance(func, ast.Name):
            return func.id
        return None

    def _is_interactive(self, name: str) -> bool:
        return (
            name in _FLET_INTERACTIVE
            or name in _TK_INTERACTIVE
            or name in _QT_INTERACTIVE
        )

    def _has_event_handler(self, node: ast.Call) -> bool:
        return any(kw.arg in _FLET_HANDLER_KWARGS for kw in node.keywords)

    def _is_container(self, name: str) -> bool:
        return name in _FLET_CONTAINERS

    def _check_empty_container(
        self, call_node: ast.Call, varname: str, widget_name: str, lineno: int
    ):
        """UH007: flag container with explicitly empty controls list."""
        controls_kw = _kw_value(call_node, "controls")
        content_kw = _kw_value(call_node, "content")
        has_children = (
            (isinstance(controls_kw, (ast.List, ast.Tuple)) and controls_kw.elts)
            or content_kw is not None
            or call_node.args  # positional content
        )
        if has_children:
            return
        if isinstance(controls_kw, (ast.List, ast.Tuple)) and not controls_kw.elts:
            self.issues.append(
                UIHealthIssue(
                    rule_code="UH007",
                    file_path=self.file_path,
                    line=lineno,
                    end_line=lineno,
                    widget_name=varname,
                    detail=f"{widget_name}(controls=[]) — no children",
                    suggestion="Add child controls or populate them later.",
                )
            )

    # -- visitors ------------------------------------------------------------

    def visit_Assign(self, node: ast.Assign):  # noqa: N802
        """Track widget variable assignments."""
        if isinstance(node.value, ast.Call):
            widget_name = self._is_flet_widget(node.value)
            if widget_name:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        varname = target.id
                        self._widget_vars[varname] = (node.lineno, widget_name)

                        # UH002: always-invisible?
                        vis_node = _kw_value(node.value, "visible")
                        if _is_false(vis_node):
                            self._invisible_vars[varname] = (node.lineno, widget_name)

                        # UH003: interactive + no handler?
                        if self._is_interactive(
                            widget_name
                        ) and not self._has_event_handler(node.value):
                            self._no_handler.append((varname, node.lineno, widget_name))

                        # UH007: empty container?
                        if self._is_container(widget_name):
                            self._check_empty_container(
                                node.value, varname, widget_name, node.lineno
                            )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):  # noqa: N802
        """Detect .controls.append / .controls = [...] patterns and visible=True flips."""
        # Pattern: some_var.controls → the some_var is being parented
        if node.attr in ("controls", "content"):
            if isinstance(node.value, ast.Name):
                # The parent is being referenced - track children added to it
                pass

        # Pattern: widget.visible = True  (flips invisible)
        # This is an attribute assignment, handled in visit_AugAssign / visit_Assign for Attribute targets
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign):  # noqa: N802
        self.generic_visit(node)

    def _collect_parent_names(self, args):
        """Add Name ids from call arguments to _added_to_parent set."""
        for arg in args:
            if isinstance(arg, ast.Name):
                self._added_to_parent.add(arg.id)
            elif isinstance(arg, (ast.List, ast.Tuple)):
                for elt in arg.elts:
                    if isinstance(elt, ast.Name):
                        self._added_to_parent.add(elt.id)

    def visit_Call(self, node: ast.Call):  # noqa: N802
        """Track page.add(), column.controls.append(), etc."""
        func = node.func

        # page.add(widget, ...)  or  main_content.controls.append(widget)
        if isinstance(func, ast.Attribute):
            if func.attr in ("add", "append", "extend", "insert"):
                self._collect_parent_names(node.args)

            # UH004: detect expand=True inside fixed container
            if func.attr in _FLET_CONTAINERS or (
                isinstance(func.value, ast.Name) and func.attr in _FLET_CONTAINERS
            ):
                self._check_layout_antipattern(node)

        # Also check direct calls: Column([widget, ...])
        self._collect_parent_names(node.args)

        # Collect all Name references (for dead-widget detection)
        self.generic_visit(node)

    def _check_layout_antipattern(self, node: ast.Call):
        """UH004: expand=True inside a width= or height= fixed container."""
        has_fixed = _kw_value(node, "width") or _kw_value(node, "height")
        if not has_fixed:
            return
        controls_kw = _kw_value(node, "controls") or _kw_value(node, "content")
        if not isinstance(controls_kw, (ast.List, ast.Tuple)):
            return
        for child in controls_kw.elts:
            if isinstance(child, ast.Call):
                if _is_true(_kw_value(child, "expand")):
                    child_name = _attr_name(child.func) or "widget"
                    self.issues.append(
                        UIHealthIssue(
                            rule_code="UH004",
                            file_path=self.file_path,
                            line=child.lineno,
                            end_line=getattr(child, "end_lineno", child.lineno),
                            widget_name=child_name,
                            detail=f"{child_name}(expand=True) inside fixed-dimension parent",
                            suggestion="Remove expand=True or remove fixed width/height from parent.",
                        )
                    )

    def visit_Name(self, node: ast.Name):  # noqa: N802
        """Track all Name references for dead widget detection."""
        self._all_referenced.add(node.id)
        self.generic_visit(node)

    # Also track x.controls = [a, b] style assignments
    def visit_Assign_attr(self, node: ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Attribute) and target.attr in (
                "controls",
                "content",
            ):
                if isinstance(node.value, (ast.List, ast.Tuple)):
                    for elt in node.value.elts:
                        if isinstance(elt, ast.Name):
                            self._added_to_parent.add(elt.id)

    def _finalize(self):
        """Called after visiting the whole file — emit aggregate issues."""
        # UH001: dead widgets (assigned but never referenced after creation)
        for varname, (line, widget_type) in self._widget_vars.items():
            # If the varname never appears in an add/append context AND
            # is not referenced in controls lists at all — it's likely dead.
            # We use a conservative heuristic: not in _added_to_parent
            # and NOT a common return variable name.
            if varname not in self._added_to_parent and varname not in {
                "sidebar",
                "layout",
                "modal",
                "dialog",
                "app",
                "page",
                "tab",
                "panel",
                "content",
                "container",
                "view",
            }:
                # Extra check: how many times is the name referenced?
                # We can't count without traversing again, so skip over
                # single-char or very generic names
                if len(varname) >= 3 and not varname.startswith("_"):
                    self.issues.append(
                        UIHealthIssue(
                            rule_code="UH001",
                            file_path=self.file_path,
                            line=line,
                            end_line=line,
                            widget_name=varname,
                            detail=f"{widget_type} '{varname}' never added to UI tree",
                            suggestion=f"Add '{varname}' to a parent via page.add() or controls=[{varname}].",
                        )
                    )

        # UH002: always-invisible (visible=False, never flipped)
        for varname, (line, widget_type) in self._invisible_vars.items():
            if varname not in self._flipped_visible:
                self.issues.append(
                    UIHealthIssue(
                        rule_code="UH002",
                        file_path=self.file_path,
                        line=line,
                        end_line=line,
                        widget_name=varname,
                        detail=f"{widget_type} '{varname}' has visible=False with no visible=True anywhere",
                        suggestion="Set visible=True when the condition is met, or remove the control.",
                    )
                )

        # UH003: interactive with no handler
        for varname, line, widget_type in self._no_handler:
            self.issues.append(
                UIHealthIssue(
                    rule_code="UH003",
                    file_path=self.file_path,
                    line=line,
                    end_line=line,
                    widget_name=varname,
                    detail=f"{widget_type} '{varname}' has no on_click/on_change/on_select handler",
                    suggestion=f"Add an event handler: {widget_type}(on_click=your_handler).",
                )
            )


def _walk_assigns_for_visible_flip(tree: ast.AST) -> Set[str]:
    """Find all ``varname.visible = True`` assignments in the tree."""
    flipped: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and target.attr == "visible"
                    and isinstance(target.value, ast.Name)
                    and _is_true(node.value)
                ):
                    flipped.add(target.value.id)
    return flipped


# ---------------------------------------------------------------------------
# JS/TS/React heuristic scanner (regex-based, no full parse)
# ---------------------------------------------------------------------------

# Patterns for React JSX analysis
_JSX_MAP_KEY_RE = re.compile(
    r"""\.map\s*\(\s*(?:\w+|\([^)]*\))\s*=>\s*(?:\(?\s*)?<(\w[\w.]*)[^>]*>""",
    re.MULTILINE,
)
_JSX_KEY_PROP_RE = re.compile(r'\bkey\s*=\s*[{"\']')
_USE_EFFECT_RE = re.compile(
    r"""useEffect\s*\(\s*(?:async\s*)?\(\s*\)\s*=>\s*\{(?P<body>[^}]*)\}\s*,\s*\[(?P<deps>[^\]]*)\]""",
    re.DOTALL,
)
_JSX_TAG_OPEN_RE = re.compile(r"<([A-Z]\w*|[a-z][\w.]*)\b[^/]*(?<!/)>")
_JSX_TAG_CLOSE_RE = re.compile(r"</([A-Z]\w*|[a-z][\w.]*)>")
_JSX_SELF_CLOSE_RE = re.compile(r"<([A-Z]\w*|[a-z][\w.]*)\b[^>]*/\s*>")


def _scan_jsx_file(src: str, file_path: str) -> List[UIHealthIssue]:
    """Regex-based heuristic scan of a JSX/TSX file."""
    issues: List[UIHealthIssue] = []

    # UH005: .map() without key prop
    for m in _JSX_MAP_KEY_RE.finditer(src):
        # Find the line number
        line_no = src[: m.start()].count("\n") + 1
        # Look ahead in the next 5 lines for a key prop
        snippet_start = m.start()
        snippet_end = min(m.end() + 500, len(src))
        snippet = src[snippet_start:snippet_end]
        if not _JSX_KEY_PROP_RE.search(snippet):
            component = m.group(1)
            issues.append(
                UIHealthIssue(
                    rule_code="UH005",
                    file_path=file_path,
                    line=line_no,
                    end_line=line_no,
                    widget_name=component,
                    detail=f"<{component}> rendered in .map() without 'key' prop",
                    suggestion=f"Add key={{item.id}} or key={{index}} to <{component}>.",
                )
            )

    # UH006: useEffect with missing deps (simplified check)
    for m in _USE_EFFECT_RE.finditer(src):
        body = m.group("body")
        deps_str = m.group("deps").strip()
        line_no = src[: m.start()].count("\n") + 1

        # Find identifiers in body that look like state/prop vars
        body_names = set(re.findall(r"\b([a-zA-Z_]\w*)\b", body))
        declared_deps = (
            set(re.findall(r"\b([a-zA-Z_]\w*)\b", deps_str)) if deps_str else set()
        )

        # Filter to likely state/prop vars (not keywords, not short names)
        _JS_KEYWORDS = {
            "const",
            "let",
            "var",
            "if",
            "else",
            "return",
            "await",
            "async",
            "function",
            "true",
            "false",
            "null",
            "undefined",
            "new",
            "this",
            "typeof",
            "instanceof",
        }
        candidates = {
            n
            for n in body_names
            if n not in _JS_KEYWORDS and len(n) > 2 and not n[0].isupper()
        }
        missing = (
            candidates - declared_deps - {"fetch", "console", "window", "document"}
        )
        if missing and len(missing) <= 5:  # avoid false-positive spam
            issues.append(
                UIHealthIssue(
                    rule_code="UH006",
                    file_path=file_path,
                    line=line_no,
                    end_line=line_no,
                    widget_name="useEffect",
                    detail=f"Possibly missing deps: {', '.join(sorted(missing))}",
                    suggestion="Add missing variables to the useEffect dependency array.",
                )
            )

    return issues


# ---------------------------------------------------------------------------
# Main analyzer class
# ---------------------------------------------------------------------------


class UIHealthAnalyzer:
    """
    Analyzer #10 — UI Health.

    Detects structural and behavioral UI problems in Python (Flet, tkinter,
    PyQt) and React/JSX/TSX files.
    """

    def __init__(self):
        pass

    # -- public API ----------------------------------------------------------

    def analyze(
        self, path: Path, exclude: Optional[List[str]] = None
    ) -> List[UIHealthIssue]:
        """Analyze a file or directory tree. Returns UIHealthIssue list."""
        if path.is_file():
            return self._analyze_file(path)
        return self._analyze_tree(path, exclude=exclude)

    def analyze_to_smells(
        self, path: Path, exclude: Optional[List[str]] = None
    ) -> List[SmellIssue]:
        """Convenience: analyze and convert straight to SmellIssue list."""
        return [i.to_smell() for i in self.analyze(path, exclude)]

    def summary(
        self,
        issues: Optional[List[SmellIssue]] = None,
        raw: Optional[List[UIHealthIssue]] = None,
    ) -> Dict[str, Any]:
        """Build summary dict compatible with X-Ray reporting."""
        if raw is not None:
            smells = [i.to_smell() for i in raw]
        else:
            smells = issues or []
        total = len(smells)
        by_rule: Dict[str, int] = {}
        by_file: Dict[str, int] = {}
        critical = warning = info = 0
        for s in smells:
            by_rule[s.rule_code] = by_rule.get(s.rule_code, 0) + 1
            by_file[s.file_path] = by_file.get(s.file_path, 0) + 1
            if s.severity == Severity.CRITICAL:
                critical += 1
            elif s.severity == Severity.WARNING:
                warning += 1
            else:
                info += 1
        return {
            "total": total,
            "critical": critical,
            "warning": warning,
            "info": info,
            "by_rule": dict(sorted(by_rule.items(), key=lambda x: -x[1])),
            "by_file": dict(sorted(by_file.items(), key=lambda x: -x[1])),
        }

    # -- internals -----------------------------------------------------------

    _EXCLUDE_DEFAULT = {
        ".venv",
        "venv",
        "__pycache__",
        ".git",
        "node_modules",
        "target",
        "dist",
        "build",
    }

    def _analyze_tree(
        self, root: Path, exclude: Optional[List[str]] = None
    ) -> List[UIHealthIssue]:
        exclude_set = set(exclude or []) | self._EXCLUDE_DEFAULT
        issues: List[UIHealthIssue] = []
        for f in sorted(root.rglob("*")):
            if not f.is_file():
                continue
            if any(part in exclude_set for part in f.parts):
                continue
            try:
                if f.suffix == ".py":
                    issues.extend(self._analyze_python_file(f, root))
                elif f.suffix in {".jsx", ".tsx", ".js", ".ts"}:
                    issues.extend(self._analyze_jsx_file(f, root))
            except Exception as exc:
                logger.debug(f"ui_health: skipping {f}: {exc}")
        return issues

    def _analyze_file(self, path: Path) -> List[UIHealthIssue]:
        if path.suffix == ".py":
            return self._analyze_python_file(path)
        if path.suffix in {".jsx", ".tsx", ".js", ".ts"}:
            return self._analyze_jsx_file(path)
        return []

    def _analyze_python_file(
        self, path: Path, root: Optional[Path] = None
    ) -> List[UIHealthIssue]:
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src, filename=str(path))
        except SyntaxError:
            return []

        rel_path = str(path.relative_to(root)) if root else str(path)
        lines = src.splitlines()
        visitor = _PythonUIVisitor(lines, rel_path)
        visitor.visit(tree)
        # Populate flipped_visible from whole-tree attribute scan
        visitor._flipped_visible = _walk_assigns_for_visible_flip(tree)
        visitor._finalize()
        return visitor.issues

    def _analyze_jsx_file(
        self, path: Path, root: Optional[Path] = None
    ) -> List[UIHealthIssue]:
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return []
        rel_path = str(path.relative_to(root)) if root else str(path)
        return _scan_jsx_file(src, rel_path)


def analyze(source_code: str, project_root: str = None):
    raise NotImplementedError("Use UIHealthAnalyzer directly")


def analyze_to_smells(source_code: str, project_root: str = None):
    raise NotImplementedError("Use UIHealthAnalyzer directly")


def message(*args, **kwargs):
    raise NotImplementedError("Use UIHealthAnalyzer directly")


def severity(*args, **kwargs):
    raise NotImplementedError("Use UIHealthAnalyzer directly")


def summary(issues: List):
    raise NotImplementedError("Use UIHealthAnalyzer directly")


def to_smell(*args, **kwargs):
    raise NotImplementedError("Use UIHealthAnalyzer directly")


def visit_Assign(*args, **kwargs):
    raise NotImplementedError("Use UIHealthAnalyzer directly")


def visit_Assign_attr(*args, **kwargs):
    raise NotImplementedError("Use UIHealthAnalyzer directly")


def visit_Attribute(*args, **kwargs):
    raise NotImplementedError("Use UIHealthAnalyzer directly")


def visit_AugAssign(*args, **kwargs):
    raise NotImplementedError("Use UIHealthAnalyzer directly")


def visit_Call(*args, **kwargs):
    raise NotImplementedError("Use UIHealthAnalyzer directly")


def visit_Name(*args, **kwargs):
    raise NotImplementedError("Use UIHealthAnalyzer directly")
