#!/usr/bin/env python3
"""
X-Ray Portability Audit — Deep analysis for cross-machine portability.

Checks:
  1. Hardcoded user paths (C:\\Users\\<name>\\...)
  2. Hardcoded C:\\AI\\ paths without env-var/discovery fallbacks
  3. requirements.txt completeness (imports vs declared deps)
  4. Missing auto-install bootstrap patterns

Usage:
  python -m xray.portability_audit /path/to/project
  python -m xray.portability_audit /path/to/project --fix
  python -m xray.portability_audit /path/to/projects_root --all
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from dataclasses import dataclass, field

from xray.constants import SKIP_DIRS as _SKIP_DIRS

# Well-known stdlib top-level modules (subset — enough for common false positives)
_STDLIB = {
    "abc",
    "argparse",
    "ast",
    "asyncio",
    "base64",
    "binascii",
    "bisect",
    "builtins",
    "calendar",
    "cgi",
    "cmd",
    "codecs",
    "collections",
    "colorsys",
    "concurrent",
    "configparser",
    "contextlib",
    "copy",
    "copyreg",
    "cProfile",
    "csv",
    "ctypes",
    "curses",
    "dataclasses",
    "datetime",
    "dbm",
    "decimal",
    "difflib",
    "dis",
    "distutils",
    "email",
    "enum",
    "errno",
    "faulthandler",
    "filecmp",
    "fileinput",
    "fnmatch",
    "fractions",
    "ftplib",
    "functools",
    "gc",
    "getopt",
    "getpass",
    "gettext",
    "glob",
    "gzip",
    "hashlib",
    "heapq",
    "hmac",
    "html",
    "http",
    "idlelib",
    "imaplib",
    "importlib",
    "inspect",
    "io",
    "ipaddress",
    "itertools",
    "json",
    "keyword",
    "lib2to3",
    "linecache",
    "locale",
    "logging",
    "lzma",
    "mailbox",
    "math",
    "mimetypes",
    "mmap",
    "multiprocessing",
    "netrc",
    "numbers",
    "operator",
    "optparse",
    "os",
    "pathlib",
    "pdb",
    "pickle",
    "pickletools",
    "pipes",
    "pkgutil",
    "platform",
    "plistlib",
    "poplib",
    "posixpath",
    "pprint",
    "profile",
    "pstats",
    "pty",
    "pwd",
    "py_compile",
    "pyclbr",
    "pydoc",
    "queue",
    "quopri",
    "random",
    "re",
    "readline",
    "reprlib",
    "resource",
    "rlcompleter",
    "runpy",
    "sched",
    "secrets",
    "select",
    "selectors",
    "shelve",
    "shlex",
    "shutil",
    "signal",
    "site",
    "smtplib",
    "sndhdr",
    "socket",
    "socketserver",
    "sqlite3",
    "ssl",
    "stat",
    "statistics",
    "string",
    "stringprep",
    "struct",
    "subprocess",
    "sunau",
    "symtable",
    "sys",
    "sysconfig",
    "syslog",
    "tabnanny",
    "tarfile",
    "tempfile",
    "test",
    "textwrap",
    "threading",
    "time",
    "timeit",
    "tkinter",
    "token",
    "tokenize",
    "trace",
    "traceback",
    "tracemalloc",
    "tty",
    "turtle",
    "turtledemo",
    "types",
    "typing",
    "unicodedata",
    "unittest",
    "urllib",
    "uu",
    "uuid",
    "venv",
    "warnings",
    "wave",
    "weakref",
    "webbrowser",
    "winreg",
    "winsound",
    "wsgiref",
    "xml",
    "xmlrpc",
    "zipapp",
    "zipfile",
    "zipimport",
    "zlib",
    # Common sub-packages that look like top-level
    "encodings",
    "_thread",
    "__future__",
    "typing_extensions",
}

# Map from import name → pip package name (common mismatches)
_IMPORT_TO_PKG = {
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "sklearn": "scikit-learn",
    "skimage": "scikit-image",
    "bs4": "beautifulsoup4",
    "yaml": "PyYAML",
    "attr": "attrs",
    "gi": "PyGObject",
    "wx": "wxPython",
    "serial": "pyserial",
    "usb": "pyusb",
    "Crypto": "pycryptodome",
    "jose": "python-jose",
    "jwt": "PyJWT",
    "dotenv": "python-dotenv",
    "magic": "python-magic",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "lxml": "lxml",
    "dateutil": "python-dateutil",
    "google": "google-api-python-client",
    "flet": "flet",
    "nicegui": "nicegui",
    "uvicorn": "uvicorn",
    "fastapi": "fastapi",
    "starlette": "starlette",
    "httpx": "httpx",
    "aiohttp": "aiohttp",
    "requests": "requests",
    "flask": "flask",
    "django": "django",
    "numpy": "numpy",
    "np": "numpy",
    "pandas": "pandas",
    "pd": "pandas",
    "scipy": "scipy",
    "matplotlib": "matplotlib",
    "plt": "matplotlib",
    "seaborn": "seaborn",
    "torch": "torch",
    "tensorflow": "tensorflow",
    "tf": "tensorflow",
    "transformers": "transformers",
    "datasets": "datasets",
    "accelerate": "accelerate",
    "onnx": "onnx",
    "onnxruntime": "onnxruntime",
    "tqdm": "tqdm",
    "rich": "rich",
    "click": "click",
    "typer": "typer",
    "pydantic": "pydantic",
    "sqlalchemy": "sqlalchemy",
    "peewee": "peewee",
    "celery": "celery",
    "redis": "redis",
    "pymongo": "pymongo",
    "boto3": "boto3",
    "paramiko": "paramiko",
    "fabric": "fabric",
    "psutil": "psutil",
    "watchdog": "watchdog",
    "colorama": "colorama",
    "tabulate": "tabulate",
    "jinja2": "Jinja2",
    "pytest": "pytest",
    "hypothesis": "hypothesis",
    "mypy": "mypy",
    "ruff": "ruff",
    "black": "black",
    "isort": "isort",
    "streamlit": "streamlit",
    "gradio": "gradio",
    "sentence_transformers": "sentence-transformers",
    "qdrant_client": "qdrant-client",
    "chromadb": "chromadb",
    "langchain": "langchain",
    "openai": "openai",
    "anthropic": "anthropic",
    "llama_cpp": "llama-cpp-python",
    "TTS": "TTS",
    "sounddevice": "sounddevice",
    "soundfile": "soundfile",
    "librosa": "librosa",
    "whisper": "openai-whisper",
    "faster_whisper": "faster-whisper",
    "deep_translator": "deep-translator",
    "ctranslate2": "ctranslate2",
    "pyaudio": "PyAudio",
    "pyperclip": "pyperclip",
    "pygments": "Pygments",
    "deskew": "deskew",
    "pytesseract": "pytesseract",
    "easyocr": "easyocr",
    "yfinance": "yfinance",
    "plotly": "plotly",
    "vlc": "python-vlc",
    "fitz": "PyMuPDF",
    "cpuinfo": "py-cpuinfo",
    "pynvml": "nvidia-ml-py3",
    "pystray": "pystray",
    "telethon": "Telethon",
    "duckduckgo_search": "duckduckgo-search",
    "googlesearch": "googlesearch-python",
    "parselmouth": "praat-parselmouth",
    "pyworld": "pyworld",
    "av": "av",
    "tiktoken": "tiktoken",
    "edge_tts": "edge-tts",
    "piper": "piper-tts",
    "resemblyzer": "resemblyzer",
    "soxr": "soxr",
    "pyodbc": "pyodbc",
    "hl7apy": "hl7apy",
    "surya": "surya-ocr",
    "playwright": "playwright",
    "exllamav2": "exllamav2",
    "mlx_lm": "mlx-lm",
    "mlx_vlm": "mlx-vlm",
    "torchaudio": "torchaudio",
    "torchvision": "torchvision",
    "huggingface_hub": "huggingface-hub",
    "sentencepiece": "sentencepiece",
    "pysrt": "pysrt",
}

# ── Data classes ──────────────────────────────────────────────────────────


@dataclass
class PortIssue:
    """Single portability issue."""

    category: str  # "hardcoded_path" | "missing_dep" | "env_crash"
    severity: str  # "HIGH" | "MEDIUM" | "LOW"
    file: str
    line: int
    text: str
    description: str
    fix_suggestion: str
    fixable: bool = False

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "severity": self.severity,
            "file": self.file,
            "line": self.line,
            "text": self.text[:200],
            "description": self.description,
            "fix_suggestion": self.fix_suggestion,
            "fixable": self.fixable,
        }

    def __str__(self) -> str:
        return f"[{self.severity}] {self.category}: {self.file}:{self.line} — {self.description}"


@dataclass
class AuditResult:
    """Full audit result for a project."""

    project: str
    project_path: str
    issues: list[PortIssue] = field(default_factory=list)
    missing_deps: list[str] = field(default_factory=list)
    files_scanned: int = 0
    has_requirements: bool = False
    has_auto_install: bool = False

    @property
    def high_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "HIGH")

    @property
    def ok(self) -> bool:
        return self.high_count == 0

    def summary(self) -> str:
        status = "PASS" if self.ok else "FAIL"
        counts = f"{self.high_count} HIGH, {sum(1 for i in self.issues if i.severity == 'MEDIUM')} MEDIUM"
        deps = f", {len(self.missing_deps)} missing deps" if self.missing_deps else ""
        return f"[{status}] {self.project}: {len(self.issues)} issues ({counts}){deps} | {self.files_scanned} files"

    def to_dict(self) -> dict:
        return {
            "project": self.project,
            "project_path": self.project_path,
            "summary": self.summary(),
            "issues": [i.to_dict() for i in self.issues],
            "missing_deps": self.missing_deps,
            "files_scanned": self.files_scanned,
            "has_requirements": self.has_requirements,
            "has_auto_install": self.has_auto_install,
        }


# ── Path scanning ─────────────────────────────────────────────────────────

# Patterns that indicate a line is in a comment or docstring region
_COMMENT_LINE_RE = re.compile(r"^\s*#")

# Hardcoded user paths: C:\Users\<username>\...
_USER_PATH_RE = re.compile(
    r"""['"]((?:r\s*)?)?(?:C:[/\\]Users[/\\])(\w+)([/\\][^'"]+)?['"]"""
    r"""|(?:Path\s*\(\s*(?:r\s*)?['"])(C:[/\\]Users[/\\])(\w+)([/\\][^'"]+)?['"]""",
    re.IGNORECASE,
)
_USER_PATH_SIMPLE = re.compile(
    r"""C:[/\\]Users[/\\]\w+""",
    re.IGNORECASE,
)

# C:\AI\... paths
_CAI_PATH_RE = re.compile(
    r"""C:[/\\]AI[/\\]""",
    re.IGNORECASE,
)

# Generic absolute Windows paths (not in comments/docstrings)
_ABS_WIN_RE = re.compile(
    r"""[A-Z]:[/\\](?!Windows[/\\]|Program\s*Files|Users[/\\]|AI[/\\])""",
)


def _in_docstring(lines: list[str], idx: int) -> bool:
    """Rough check if line idx is inside a triple-quoted docstring."""
    triple_count = 0
    for i in range(idx):
        line = lines[i]
        triple_count += line.count('"""') + line.count("'''")
    return triple_count % 2 == 1


def _is_in_discovery_chain(lines: list[str], idx: int) -> bool:
    """Check if the line is part of a candidate/discovery list that checks existence."""
    # Look ±5 lines for .is_dir(), .is_file(), .exists(), or in a for loop
    context = lines[max(0, idx - 5) : min(len(lines), idx + 6)]
    context_text = "\n".join(context)
    return bool(re.search(r"\.(is_dir|is_file|exists)\s*\(\s*\)", context_text))


def scan_hardcoded_paths(filepath: str, project_root: str) -> list[PortIssue]:
    """Scan a single file for hardcoded non-portable paths."""
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except (OSError, PermissionError):
        return []

    lines = content.splitlines()
    issues: list[PortIssue] = []
    rel = os.path.relpath(filepath, project_root).replace("\\", "/")

    for idx, line in enumerate(lines):
        # Skip comments
        if _COMMENT_LINE_RE.match(line):
            continue
        # Skip docstring interiors
        if _in_docstring(lines, idx):
            continue

        line_num = idx + 1

        # --- PORT-001: User-specific paths ---
        if _USER_PATH_SIMPLE.search(line):
            # Skip if it's in a discovery chain
            if _is_in_discovery_chain(lines, idx):
                continue
            # Skip test assertion strings (assert _fwd("C:\Users\...") == ...)
            stripped = line.strip()
            if stripped.startswith("assert ") and "==" in stripped:
                continue
            # Skip test fixture data: js_esc(), _fwd(), or similar test calls
            if re.search(r"(js_esc|_fwd|esc)\s*\(", stripped):
                continue
            # Skip XSS/injection attack test strings
            if re.search(r"<script>|&amp;|&quot;|xss|injection|attack", stripped, re.IGNORECASE):
                continue
            # Skip generic test paths like C:\Users\test (no real username >5 chars)
            m = re.search(r"C:[/\\]Users[/\\](\w+)", line)
            if m:
                username = m.group(1)
                # Skip generic test usernames
                if username.lower() in ("test", "user", "example", "public", "default"):
                    continue
            # Skip if inside a list of test path strings (common in path-test files)
            if re.search(r'r"C:\\\\Users\\\\test|r"C:\\Users\\test', stripped):
                continue
            # Skip UI placeholder text (e.g. placeholder with a path like /Users/Me/)
            if "placeholder" in stripped.lower():
                continue
            issues.append(
                PortIssue(
                    category="hardcoded_path",
                    severity="HIGH",
                    file=rel,
                    line=line_num,
                    text=line.strip()[:120],
                    description="User-specific path breaks on other machines",
                    fix_suggestion="Use Path.home(), Path(__file__).parent, or env vars",
                    fixable=True,
                )
            )

        # --- PORT-002: C:\AI paths ---
        elif _CAI_PATH_RE.search(line):
            if _is_in_discovery_chain(lines, idx):
                continue
            # Skip mock/test strings that use fake paths
            stripped = line.strip()
            if re.search(r"(mock|Mock|MagicMock|FakeInference|spec=|lambda\s+self)", stripped):
                continue
            # Skip test paths with synthetic names like test.gguf, model_a.gguf, x.gguf
            if re.search(r"C:[/\\]AI[/\\]\S*(?:test|model[_.]|fake|dummy|[a-z]\.gguf)", stripped, re.IGNORECASE):
                continue
            # In test files, skip simple string assignments used as test fixtures
            if os.path.basename(filepath).startswith("test_") and re.search(
                r'^\s*(path|model_path)\s*=\s*["\']', stripped
            ):
                continue
            issues.append(
                PortIssue(
                    category="hardcoded_path",
                    severity="HIGH" if "Path(" in line or "= " in line else "MEDIUM",
                    file=rel,
                    line=line_num,
                    text=line.strip()[:120],
                    description="Hardcoded C:\\AI path — not portable",
                    fix_suggestion="Use ZENAI_MODEL_DIR env var → Path.home() / 'AI' fallback",
                    fixable=True,
                )
            )

    return issues


# ── Requirements analysis ─────────────────────────────────────────────────


def _extract_imports(filepath: str) -> set[str]:
    """Extract top-level imported module names from a Python file via AST."""
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            source = f.read()
        tree = ast.parse(source, filename=filepath)
    except (SyntaxError, ValueError, RecursionError, OSError):
        return set()

    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    return imports


def _parse_requirements(req_path: str) -> set[str]:
    """Parse requirements.txt and return normalized package names."""
    pkgs = set()
    try:
        with open(req_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("-"):
                    continue
                # Handle extras: package[extra]>=version
                pkg = re.split(r"[>=<!\[;]", line)[0].strip()
                if pkg:
                    pkgs.add(pkg.lower().replace("-", "_").replace(".", "_"))
    except (OSError, PermissionError):
        pass
    return pkgs


def _normalize_pkg(name: str) -> str:
    """Normalize a package name for comparison."""
    return name.lower().replace("-", "_").replace(".", "_")


def check_requirements(project_root: str) -> tuple[bool, list[str], bool]:
    """Check if requirements.txt exists and covers all third-party imports.

    Returns: (has_requirements, missing_packages, has_auto_install)
    """
    req_path = os.path.join(project_root, "requirements.txt")
    has_req = os.path.isfile(req_path)

    # Check for auto-install pattern
    has_auto = False
    for entry in ("__init__.py", "start_llm.py", "run.py", "main.py", "app.py", "server.py"):
        fp = os.path.join(project_root, entry)
        if os.path.isfile(fp):
            try:
                with open(fp, encoding="utf-8", errors="replace") as f:
                    text = f.read(4000)
                if "pip install" in text or "check_and_install" in text or "_ensure_deps" in text:
                    has_auto = True
                    break
            except OSError:
                pass

    if not has_req:
        return False, [], has_auto

    declared = _parse_requirements(req_path)

    # Collect all imports across all .py files
    all_imports: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fname in filenames:
            if fname.endswith(".py"):
                fpath = os.path.join(dirpath, fname)
                all_imports |= _extract_imports(fpath)

    # Filter out stdlib and local imports
    local_modules = set()
    for entry in os.listdir(project_root):
        if entry.endswith(".py"):
            local_modules.add(entry[:-3])
        elif os.path.isdir(os.path.join(project_root, entry)):
            if os.path.isfile(os.path.join(project_root, entry, "__init__.py")):
                local_modules.add(entry)
            # Also add dirnames that might be implicit namespace packages
            local_modules.add(entry)

    # Walk deeper: add sub-packages and sibling modules
    for _, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fname in filenames:
            if fname.endswith(".py") and fname != "__init__.py":
                local_modules.add(fname[:-3])
        for dname in dirnames:
            local_modules.add(dname)

    # Platform-specific modules that aren't pip-installable
    _PLATFORM_MODULES = {
        "msvcrt",
        "winreg",
        "winsound",
        "termios",
        "pty",
        "resource",
        "pwd",
        "grp",
        "fcntl",
        "atexit",
        "compileall",
        "readline",
        "win32com",
        "win32api",
        "win32gui",
        "win32con",
        "pywintypes",
        "pythoncom",
        "wmi",
    }
    local_modules |= _PLATFORM_MODULES

    # Also consider sibling project directories as "local" imports
    # (common pattern: sys.path.append(parent) then import SiblingProject)
    parent_dir = os.path.dirname(project_root)
    if parent_dir:
        for entry in os.listdir(parent_dir):
            sibling = os.path.join(parent_dir, entry)
            if os.path.isdir(sibling) and entry != os.path.basename(project_root):
                local_modules.add(entry)

    # Optional packages that are auto-installed at runtime (not required in reqs)
    _OPTIONAL_AUTO_INSTALL = {
        "openvoice",
        "cosyvoice",
        "f5_tts",
        "argostranslate",
        "pyamdgpuinfo",
    }  # AMD GPU detection — platform-specific
    local_modules |= _OPTIONAL_AUTO_INSTALL

    missing = []
    for imp in sorted(all_imports):
        if imp in _STDLIB:
            continue
        if imp in local_modules:
            continue
        # Check if declared
        norm = _normalize_pkg(imp)
        if norm in declared:
            continue
        # Check via known mapping
        pkg_name = _IMPORT_TO_PKG.get(imp)
        if pkg_name and _normalize_pkg(pkg_name) in declared:
            continue
        # Check if any declared package contains the import name
        if any(norm in d or d in norm for d in declared):
            continue
        missing.append(imp)

    return True, missing, has_auto


# ── Full project audit ────────────────────────────────────────────────────


def audit_project(project_path: str) -> AuditResult:
    """Run full portability audit on a single project."""
    project_name = os.path.basename(project_path)
    result = AuditResult(
        project=project_name,
        project_path=project_path,
    )

    # 1. Scan all Python files for hardcoded paths
    for dirpath, dirnames, filenames in os.walk(project_path):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fname in filenames:
            if fname.endswith(".py"):
                fpath = os.path.join(dirpath, fname)
                result.files_scanned += 1
                issues = scan_hardcoded_paths(fpath, project_path)
                result.issues.extend(issues)

    # 2. Check requirements
    has_req, missing, has_auto = check_requirements(project_path)
    result.has_requirements = has_req
    result.has_auto_install = has_auto
    result.missing_deps = missing

    if not has_req:
        result.issues.append(
            PortIssue(
                category="missing_dep",
                severity="MEDIUM",
                file="requirements.txt",
                line=0,
                text="",
                description="No requirements.txt found — dependencies not documented",
                fix_suggestion="Create requirements.txt listing all third-party packages",
                fixable=False,
            )
        )

    if missing:
        for dep in missing:
            result.issues.append(
                PortIssue(
                    category="missing_dep",
                    severity="LOW",
                    file="requirements.txt",
                    line=0,
                    text=dep,
                    description=f"Import '{dep}' not found in requirements.txt",
                    fix_suggestion=f"Add {_IMPORT_TO_PKG.get(dep, dep)} to requirements.txt",
                    fixable=False,
                )
            )

    return result


def audit_all_projects(root: str) -> list[AuditResult]:
    """Audit all project directories under a root folder."""
    results = []
    for entry in sorted(os.listdir(root)):
        project_path = os.path.join(root, entry)
        if not os.path.isdir(project_path):
            continue
        if entry.startswith(".") or entry.startswith("_"):
            continue
        # Must have at least one .py file to be a project
        has_py = any(
            f.endswith(".py") for f in os.listdir(project_path) if os.path.isfile(os.path.join(project_path, f))
        )
        if not has_py:
            continue
        results.append(audit_project(project_path))
    return results


# ── Report formatting ─────────────────────────────────────────────────────


def format_report(results: list[AuditResult]) -> str:
    """Format audit results into a readable report."""
    lines = []
    lines.append("=" * 78)
    lines.append("  X-Ray Portability Audit Report")
    lines.append("=" * 78)
    lines.append("")

    total_issues = sum(len(r.issues) for r in results)
    total_high = sum(r.high_count for r in results)
    pass_count = sum(1 for r in results if r.ok)
    lines.append(f"  Projects: {len(results)} scanned, {pass_count} PASS, {len(results) - pass_count} FAIL")
    lines.append(f"  Issues:   {total_issues} total, {total_high} HIGH severity")
    lines.append("")

    for r in results:
        lines.append(r.summary())
        if r.issues:
            # Group by category
            by_cat: dict[str, list[PortIssue]] = {}
            for i in r.issues:
                by_cat.setdefault(i.category, []).append(i)

            for cat, cat_issues in sorted(by_cat.items()):
                for issue in cat_issues[:10]:  # limit per category
                    lines.append(f"    {issue.severity:6} {issue.file}:{issue.line} — {issue.description}")
                if len(cat_issues) > 10:
                    lines.append(f"    ... and {len(cat_issues) - 10} more {cat} issues")

        if r.missing_deps:
            lines.append(f"    Missing deps: {', '.join(r.missing_deps[:20])}")
        lines.append("")

    lines.append("=" * 78)
    return "\n".join(lines)


# ── CLI entry point ───────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="X-Ray Portability Audit — detect cross-machine portability issues")
    parser.add_argument("path", help="Project directory to audit")
    parser.add_argument("--all", action="store_true", help="Treat path as parent of multiple projects and audit all")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument("--fix", action="store_true", help="(Reserved) Auto-fix detected issues")
    args = parser.parse_args()

    target = os.path.abspath(args.path)
    if not os.path.isdir(target):
        print(f"Error: {target} is not a directory", file=sys.stderr)
        sys.exit(1)

    results = audit_all_projects(target) if args.all else [audit_project(target)]

    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2))
    else:
        print(format_report(results))

    # Exit with non-zero if any HIGH issues found
    if any(r.high_count > 0 for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
