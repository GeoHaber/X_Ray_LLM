#!/usr/bin/env python3
"""
X_RAY_Claude.py — Smart AI-Powered Code Analyzer (X-Ray 5.0)
=============================================================

Unified code quality scanner combining:
  - AST-based structural analysis (smells, duplicates)
  - Ruff linter integration (style, imports, hygiene)
  - Bandit security scanner integration (vulnerabilities)

Usage::

    python X_RAY_Claude.py --path .                     # default: smells + lint + security
    python X_RAY_Claude.py --smell                      # code smell detection only
    python X_RAY_Claude.py --duplicates                 # find similar functions
    python X_RAY_Claude.py --lint                       # Ruff linter only
    python X_RAY_Claude.py --security                   # Bandit security only
    python X_RAY_Claude.py --full-scan                  # everything (all 4 analyzers)
    python X_RAY_Claude.py --report scan_results.json   # save JSON report
    python X_RAY_Claude.py --rustify                    # rank functions for Rust porting
    python X_RAY_Claude.py --rustify --report rust.json  # save candidate report
"""

from __future__ import annotations

import argparse
import json
import sys
import os
import time
import asyncio
import concurrent.futures
from pathlib import Path
from typing import List, Tuple

from Core.types import FunctionRecord, ClassRecord
from Core.config import BANNER
from Core.inference import LLMHelper

from Analysis.ast_utils import extract_functions_from_file, collect_py_files
from Analysis.smells import CodeSmellDetector
from Analysis.duplicates import DuplicateFinder
from Analysis.lint import LintAnalyzer
from Analysis.security import SecurityAnalyzer
from Analysis.reporting import (
    print_smells, print_duplicates, print_lint_report,
    print_security_report, print_unified_grade,
)

from Core.utils import setup_logger
setup_logger()  # configure logging once — no duplicate basicConfig


# ═══════════════════════════════════════════════════════════════════════════
#  Interactive TUI — responsive, screen-adaptive, with LLM settings
# ═══════════════════════════════════════════════════════════════════════════

def _supports_interactive() -> bool:
    """Check if stdin is a real terminal (not piped)."""
    return hasattr(sys.stdin, 'isatty') and sys.stdin.isatty()


def _term_size() -> Tuple[int, int]:
    """(cols, rows) of current terminal."""
    import shutil
    return shutil.get_terminal_size((80, 24))


def _clear_line():
    """Move cursor up and clear the line."""
    print('\033[A\033[K', end='', flush=True)


def _ansi(code: str, text: str) -> str:
    """Wrap text in ANSI escape codes."""
    return f"\033[{code}m{text}\033[0m"


# ── Platform-specific raw key reader ──

def _make_key_reader():
    """Return a zero-argument callable that reads a single keypress."""
    if sys.platform == 'win32':
        import msvcrt
        def _read_key():
            ch = msvcrt.getwch()
            if ch in ('\x00', '\xe0'):
                ch2 = msvcrt.getwch()
                return {'H': 'up', 'P': 'down', 'K': 'left', 'M': 'right'}.get(ch2, 'unknown')
            if ch == ' ':          return 'space'
            if ch in ('\r', '\n'): return 'enter'
            if ch == '\t':         return 'tab'
            if ch == '\x1b':       return 'quit'
            lo = ch.lower()
            if lo == 'q': return 'quit'
            if lo == 'a': return 'all'
            if lo == 'n': return 'none'
            if lo == 's': return 'settings'
            if lo == 'h': return 'help'
            return 'unknown'
        return _read_key
    else:
        import tty, termios
        def _read_key():
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                ch = sys.stdin.read(1)
                if ch == '\x1b':
                    ch2 = sys.stdin.read(2)
                    return {'[A': 'up', '[B': 'down', '[C': 'right', '[D': 'left'}.get(ch2, 'unknown')
                if ch == ' ':          return 'space'
                if ch in ('\r', '\n'): return 'enter'
                if ch == '\t':         return 'tab'
                lo = ch.lower()
                if lo == 'q': return 'quit'
                if lo == 'a': return 'all'
                if lo == 'n': return 'none'
                if lo == 's': return 'settings'
                if lo == 'h': return 'help'
                return 'unknown'
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
        return _read_key


# ── Box-drawing helpers (adapt to screen width) ──

def _box_top(w: int) -> str:
    return _ansi("1;36", "╔" + "═" * (w - 2) + "╗")

def _box_mid(w: int) -> str:
    return _ansi("1;36", "╠" + "═" * (w - 2) + "╣")

def _box_sep(w: int) -> str:
    return _ansi("36", "╟" + "─" * (w - 2) + "╢")

def _box_bot(w: int) -> str:
    return _ansi("1;36", "╚" + "═" * (w - 2) + "╝")

def _box_line(w: int, text: str, align: str = "left") -> str:
    """A line inside a box. `text` may contain ANSI — we strip for padding."""
    import re
    visible = len(re.sub(r'\033\[[0-9;]*m', '', text))
    inner = w - 4  # 2 border + 2 padding
    if align == "center":
        pad_left = max(0, (inner - visible) // 2)
        pad_right = max(0, inner - visible - pad_left)
    else:
        pad_left = 0
        pad_right = max(0, inner - visible)
    return _ansi("36", "║") + " " + " " * pad_left + text + " " * pad_right + " " + _ansi("36", "║")


# ── Scan option definitions ──

_SCAN_OPTIONS = [
    ('smell',       'Code Smells',              '🔬', True,  'AST-based structural analysis'),
    ('duplicates',  'Duplicates',               '🔁', False, 'Find similar / copy-paste code'),
    ('lint',        'Lint (Ruff)',              '✏️',  True,  'Style, imports, hygiene'),
    ('security',    'Security (Bandit)',        '🛡️',  True,  'Vulnerability scanner'),
    ('rustify',     'Rust Score',               '🦀', False, 'Rank functions for Rust porting'),
    ('rustify_exe', 'Rustify → EXE',           '⚙️',  False, 'Full transpile + compile pipeline'),
]


def _interactive_menu() -> dict:
    """Responsive interactive TUI with scan options + LLM settings.

    Adapts layout to terminal width:
      - ≥80 cols: full two-column layout with decorations
      - <80 cols: compact single-column layout

    Navigation:
      ↑↓ move  |  Space toggle  |  Enter run  |  Tab → LLM settings
      a = all   |  n = none      |  s = settings  |  q = quit
    """
    cols, rows = _term_size()
    wide = cols >= 80
    box_w = min(cols - 4, 72) if wide else min(cols - 2, 50)
    read_key = _make_key_reader()

    selected = [d for _, _, _, d, _ in _SCAN_OPTIONS]
    cursor = 0
    page = 'scan'  # 'scan' or 'settings'

    # LLM info (lazy-loaded)
    llm_mgr = None
    hw_info = None
    model_recs = None

    def _get_llm_info():
        nonlocal llm_mgr, hw_info, model_recs
        if llm_mgr is None:
            try:
                from Core.llm_manager import LLMManager
                llm_mgr = LLMManager()
                llm_mgr.detect_all()
                hw_info = llm_mgr.hw
                from Core.llm_manager import recommend_models
                model_recs = recommend_models(hw_info)
            except Exception:
                pass
        return llm_mgr, hw_info, model_recs

    # ── Render functions ──

    def _render_scan() -> str:
        lines = []
        lines.append("")
        lines.append("  " + _box_top(box_w))
        title = _ansi("1;97", "X-RAY 5.0") + "  " + _ansi("36", "Interactive Scanner")
        lines.append("  " + _box_line(box_w, title, "center"))
        lines.append("  " + _box_mid(box_w))

        # Controls bar
        if wide:
            ctrl = (
                _ansi("90", "↑↓") + " move  "
                + _ansi("90", "Space") + " toggle  "
                + _ansi("90", "Enter") + " run  "
                + _ansi("90", "Tab/s") + " LLM settings"
            )
        else:
            ctrl = _ansi("90", "↑↓ Space Enter  s=settings  q=quit")
        lines.append("  " + _box_line(box_w, ctrl, "center"))
        lines.append("  " + _box_sep(box_w))

        # Scan options
        for i, (key, label, icon, default, desc) in enumerate(_SCAN_OPTIONS):
            mark = _ansi("1;32", "✓") if selected[i] else _ansi("90", "·")
            arrow = _ansi("1;33", "►") + " " if i == cursor else "  "
            if wide:
                line_text = f"{arrow}[{mark}] {icon} {label:<22} {_ansi('90', desc)}"
            else:
                line_text = f"{arrow}[{mark}] {label}"
            lines.append("  " + _box_line(box_w, line_text))

        lines.append("  " + _box_sep(box_w))

        # Summary bar
        count = sum(selected)
        summary = _ansi("1;97", f"{count}") + _ansi("90", f"/{len(_SCAN_OPTIONS)} selected")
        shortcuts = _ansi("90", "a") + "=all  " + _ansi("90", "n") + "=none  " + _ansi("90", "q") + "=quit"
        if wide:
            lines.append("  " + _box_line(box_w, f"{summary}    {shortcuts}"))
        else:
            lines.append("  " + _box_line(box_w, f"{summary}  {shortcuts}"))

        lines.append("  " + _box_bot(box_w))
        lines.append("")
        return '\n'.join(lines)

    def _render_settings() -> str:
        mgr, hw, models = _get_llm_info()
        lines = []
        lines.append("")
        lines.append("  " + _box_top(box_w))
        title = _ansi("1;97", "LLM & Runtime") + "  " + _ansi("36", "Settings")
        lines.append("  " + _box_line(box_w, title, "center"))
        lines.append("  " + _box_mid(box_w))

        ctrl = _ansi("90", "Tab/Esc") + " back to scan  " + _ansi("90", "Enter") + " confirm"
        lines.append("  " + _box_line(box_w, ctrl, "center"))
        lines.append("  " + _box_sep(box_w))

        # System info
        if hw:
            lines.append("  " + _box_line(box_w, _ansi("1;97", "System Profile")))
            lines.append("  " + _box_line(box_w, f"  OS:   {hw.os_name} {hw.os_version} ({hw.arch})"))
            lines.append("  " + _box_line(box_w, f"  CPU:  {hw.cpu_brand[:40]}"))
            lines.append("  " + _box_line(box_w, f"  RAM:  {hw.ram_gb:.0f} GB   Cores: {hw.cpu_cores}"))
            gpu_text = hw.gpu_name if hw.gpu_name != "none" else _ansi("90", "no GPU detected")
            lines.append("  " + _box_line(box_w, f"  GPU:  {gpu_text}"))
            avx = (_ansi("32", "AVX2 ✓") if hw.avx2 else _ansi("90", "AVX2 ✗"))
            lines.append("  " + _box_line(box_w, f"  SIMD: {avx}"))
            lines.append("  " + _box_line(box_w, f"  Tier: {hw.tier_label}"))
        else:
            lines.append("  " + _box_line(box_w, _ansi("33", "  detecting hardware...")))

        lines.append("  " + _box_sep(box_w))

        # Runtime status
        if mgr and mgr.runtime:
            rt = mgr.runtime
            lines.append("  " + _box_line(box_w, _ansi("1;97", "llama.cpp Runtime")))
            if rt.installed:
                status = _ansi("32", "✓ installed") + f"  {rt.version}  [{rt.backend}]"
                lines.append("  " + _box_line(box_w, f"  Status: {status}"))
                srv = _ansi("32", f"running :{rt.server_port}") if rt.server_running else _ansi("90", "stopped")
                lines.append("  " + _box_line(box_w, f"  Server: {srv}"))
            else:
                lines.append("  " + _box_line(box_w, _ansi("33", "  ⚠ llama.cpp not found")))
                lines.append("  " + _box_line(box_w, _ansi("90", "  Install: github.com/ggerganov/llama.cpp")))
        else:
            lines.append("  " + _box_line(box_w, _ansi("90", "  (runtime detection...)")))

        lines.append("  " + _box_sep(box_w))

        # Recommended models
        lines.append("  " + _box_line(box_w, _ansi("1;97", "Recommended Models")))
        if models:
            for i, m in enumerate(models[:4], 1):
                tag = _ansi("1;33", " ★ BEST") if i == 1 else ""
                if wide:
                    ml = f"  {i}. {m.name} ({m.params}){tag}"
                    lines.append("  " + _box_line(box_w, ml))
                    det = f"     {m.speed}  Code: {m.code_quality}  RAM: {m.ram_needed_gb:.0f}GB"
                    lines.append("  " + _box_line(box_w, _ansi("90", det)))
                else:
                    ml = f"  {i}. {m.name}{tag}"
                    lines.append("  " + _box_line(box_w, ml))
        else:
            lines.append("  " + _box_line(box_w, _ansi("90", "  (no models fit this hardware)")))

        lines.append("  " + _box_bot(box_w))
        lines.append("")
        return '\n'.join(lines)

    # ── Main loop ──

    def _draw(content: str) -> int:
        print(content, end='', flush=True)
        return content.count('\n') + 1

    display = _render_scan()
    line_count = _draw(display)

    while True:
        key = read_key()

        # Navigation
        if page == 'scan':
            if key == 'up':
                cursor = (cursor - 1) % len(_SCAN_OPTIONS)
            elif key == 'down':
                cursor = (cursor + 1) % len(_SCAN_OPTIONS)
            elif key == 'space':
                selected[cursor] = not selected[cursor]
            elif key == 'enter':
                break
            elif key in ('tab', 'settings'):
                page = 'settings'
            elif key == 'quit':
                print('\n  Cancelled.')
                sys.exit(0)
            elif key == 'all':
                selected = [True] * len(_SCAN_OPTIONS)
            elif key == 'none':
                selected = [False] * len(_SCAN_OPTIONS)
            else:
                continue
        elif page == 'settings':
            if key in ('tab', 'quit', 'settings', 'enter'):
                page = 'scan'
            else:
                continue

        # Re-render
        for _ in range(line_count):
            _clear_line()
        display = _render_settings() if page == 'settings' else _render_scan()
        line_count = _draw(display)

    print()
    return {key: selected[i] for i, (key, _, _, _, _) in enumerate(_SCAN_OPTIONS)}


def scan_codebase(root: Path, exclude: List[str] = None,
                  include: List[str] = None,
                  verbose: bool = False) -> Tuple[
        List[FunctionRecord], List[ClassRecord], List[str]]:
    """Parallel-scan the codebase, returning functions, classes, and errors."""
    py_files = collect_py_files(root, exclude, include)
    all_functions: List[FunctionRecord] = []
    all_classes: List[ClassRecord] = []
    errors: List[str] = []
    total = len(py_files)
    done = 0

    print(f"  Scanning {total} files using {os.cpu_count() or 4} threads...")

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(extract_functions_from_file, f, root): f
            for f in py_files
        }
        for future in concurrent.futures.as_completed(futures):
            funcs, clses, err = future.result()
            all_functions.extend(funcs)
            all_classes.extend(clses)
            if err:
                errors.append(f"{futures[future]}: {err}")
            done += 1
            if verbose and total > 20 and done % max(1, total // 10) == 0:
                pct = done * 100 // total
                print(f"    [{pct:3d}%] {done}/{total} files scanned...",
                      flush=True)

    return all_functions, all_classes, errors


# Reporting functions moved to Analysis.reporting


def _parse_args() -> argparse.Namespace:
    """Parse and normalise CLI arguments."""
    parser = argparse.ArgumentParser(
        description=BANNER,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--path", default=".", help="Root directory to scan")
    parser.add_argument("--smell", action="store_true", help="Run code smell detection")
    parser.add_argument("--duplicates", action="store_true", help="Run duplicate detection")
    parser.add_argument("--lint", action="store_true", help="Run Ruff linter analysis")
    parser.add_argument("--security", action="store_true", help="Run Bandit security scan")
    parser.add_argument("--full-scan", action="store_true", help="Run ALL analyses")
    parser.add_argument("--rustify", action="store_true",
                        help="Rank functions by Rust-porting suitability")
    parser.add_argument("--rustify-exe", action="store_true",
                        help="Full pipeline: scan → optimize → transpile → compile to executable")
    parser.add_argument("--use-llm", action="store_true", help="Enable LLM enrichment")
    parser.add_argument("--llm-settings", action="store_true",
                        help="Show LLM settings: hardware detection, model recommendations")
    parser.add_argument("--system-info", action="store_true",
                        help="Print hardware profile and exit")
    parser.add_argument("--report", help="Save JSON report to file")
    parser.add_argument("--exclude", nargs="*", help="Exclude directories")
    parser.add_argument("--interactive", "-i", action="store_true",
                        help="Launch interactive TUI to select scope and options")
    args = parser.parse_args()

    # ── System info mode ──
    if args.system_info:
        from Core.llm_manager import LLMManager
        mgr = LLMManager()
        mgr.detect_all()
        print(mgr.format_system_profile())
        print(mgr.format_runtime_status())
        print(mgr.format_model_recommendations())
        sys.exit(0)

    # ── LLM settings mode ──
    if args.llm_settings:
        from Core.llm_manager import LLMManager
        mgr = LLMManager(project_dir=Path(args.path).resolve())
        mgr.detect_all()
        print(mgr.format_system_profile())
        print(mgr.format_runtime_status())
        print(mgr.format_model_recommendations())
        status = mgr.check_and_prompt()
        if status.get('needs_install'):
            print("  💡 To install llama.cpp:")
            print("     https://github.com/ggerganov/llama.cpp/releases")
        if status.get('needs_upgrade'):
            print(f"  💡 Newer version available: {status['latest_version']}")
        sys.exit(0)

    # Interactive mode: launch TUI to select options
    if args.interactive and _supports_interactive():
        choices = _interactive_menu()
        args.smell = choices.get('smell', False)
        args.duplicates = choices.get('duplicates', False)
        args.lint = choices.get('lint', False)
        args.security = choices.get('security', False)
        args.rustify = choices.get('rustify', False)
        args.rustify_exe = choices.get('rustify_exe', False)
        return args

    # Auto-select: if no specific flags, run smells + lint + security (not duplicates, it's slow)
    has_specific = (args.smell or args.duplicates or args.lint
                    or args.security or args.rustify or args.rustify_exe)
    if args.full_scan or not has_specific:
        args.smell = True
        args.lint = True
        args.security = True
        if args.full_scan:
            args.duplicates = True

    return args


def _init_llm(args: argparse.Namespace, root: Path):
    """Initialize LLM helper if requested."""
    if not args.use_llm:
        return None
    llm = LLMHelper(root=root)
    if not llm.available:
        print("  [!] LLM not available. Installation required (see Core/services).")
        return None
    return llm


def _scan_codebase_phase(root: Path, args: argparse.Namespace):
    """Run codebase scanning for smells/duplicates if needed."""
    if not (args.smell or args.duplicates):
        return [], [], []
    start = time.time()
    functions, classes, errors = scan_codebase(root, exclude=args.exclude)
    duration = time.time() - start
    print(f"  Scanned {len(functions)} functions, {len(classes)} classes in {duration:.2f}s")
    return functions, classes, errors


def _run_smell_phase(args, functions, classes):
    """Run AST smell detection if requested."""
    if not args.smell:
        return None, []
    detector = CodeSmellDetector()
    print("\n  >> Analyzing Code Smells (X-Ray)...")
    smells = detector.detect(functions, classes)
    return detector, smells


def _run_duplicate_phase(args, functions):
    """Run duplicate detection if requested."""
    if not args.duplicates:
        return None
    finder = DuplicateFinder()
    print("\n  >> Detecting Duplicates (X-Ray)...")
    finder.find(functions)
    return finder


def _run_lint_phase(args, root):
    """Run Ruff lint analysis if requested."""
    if not args.lint:
        return None, []
    linter = LintAnalyzer()
    if linter.available:
        print("\n  >> Running Linter (Ruff)...")
        return linter, linter.analyze(root, exclude=args.exclude)
    print("\n  [!] Ruff not installed. Skipping lint analysis. (pip install ruff)")
    return None, []


def _run_security_phase(args, root):
    """Run Bandit security analysis if requested."""
    if not args.security:
        return None, []
    sec = SecurityAnalyzer()
    if sec.available:
        print("\n  >> Running Security Scan (Bandit)...")
        return sec, sec.analyze(root, exclude=args.exclude)
    print("\n  [!] Bandit not installed. Skipping security scan. (pip install bandit)")
    return None, []


def _run_rustify(root: Path, args: argparse.Namespace) -> dict:
    """Rank functions by Rust-porting suitability and print results."""
    from Analysis.rust_advisor import RustAdvisor

    print("\n  >> Scanning codebase for Rust candidates...")
    functions, classes, errors = scan_codebase(root, exclude=args.exclude)
    if not functions:
        print("  No functions found.")
        return {"rustify": {"candidates": []}}

    advisor = RustAdvisor()
    candidates = advisor.score(functions)
    advisor.print_candidates(candidates)

    results = {
        "rustify": {
            "total_functions": len(functions),
            "scored": len(candidates),
            "pure_count": sum(1 for c in candidates if c.is_pure),
            "candidates": [c.to_dict() for c in candidates],
        }
    }
    return results


def _run_rustify_exe(root: Path, args: argparse.Namespace) -> dict:
    """Full pipeline: scan → optimize → transpile → compile → verify.

    Produces a native Windows/Mac/Linux executable from the Python project.
    """
    from Analysis.auto_rustify import RustifyPipeline

    print("\n  " + "═" * 60)
    print("  🔧 FULL RUSTIFY PIPELINE: Python → Rust → Executable")
    print("  " + "═" * 60)

    def progress_cb(frac: float, label: str):
        bar_len = 30
        filled = int(bar_len * frac)
        bar = '█' * filled + '░' * (bar_len - filled)
        print(f"\r  [{bar}] {frac*100:5.1f}% {label:<40}", end='', flush=True)

    pipeline = RustifyPipeline(
        project_dir=root,
        mode="binary",
        min_score=3.0,
        max_candidates=100,
        exclude_dirs=args.exclude or [],
    )

    report = pipeline.run(progress_cb=progress_cb)
    print()  # newline after progress bar

    # Print results
    print(f"\n  ── Pipeline Results {'─' * 39}")
    print(f"  System:     {report.system.os_name} {report.system.arch}")
    print(f"  Target:     {report.system.rust_target}")
    print(f"  Scanned:    {report.candidates_total} functions in {report.scan_duration_s}s")
    print(f"  Selected:   {report.candidates_selected} candidates (score ≥ 3.0)")

    for phase in report.phases:
        status = phase.get('status', 'unknown')
        name = phase.get('name', '')
        icon = '✅' if status == 'ok' else '❌' if status == 'failed' else '⚠️'
        print(f"  {icon} {name}: {status}")
        if 'artefact' in phase and phase['artefact']:
            print(f"     → Executable: {phase['artefact']}")

    if report.compile_result and report.compile_result.success:
        exe = report.compile_result.artefact_path
        print(f"\n  \033[1;32m✓ SUCCESS\033[0m — Executable built: {exe}")
        print(f"  Run it:  {exe} --help")
    elif report.errors:
        print(f"\n  \033[1;31m✗ ERRORS:\033[0m")
        for err in report.errors[:5]:
            print(f"    {err[:200]}")

    return {"rustify_exe": report.to_dict()}


async def _run_full_scan(root: Path, args: argparse.Namespace) -> dict:
    """Execute all requested scan phases and return the results dict."""
    # ── Rustify modes ──
    if args.rustify_exe:
        return _run_rustify_exe(root, args)
    if args.rustify:
        return _run_rustify(root, args)

    llm = _init_llm(args, root)
    functions, classes, errors = _scan_codebase_phase(root, args)

    results: dict = {}
    all_issues = []

    detector, smells = _run_smell_phase(args, functions, classes)
    all_issues.extend(smells)

    finder = _run_duplicate_phase(args, functions)

    linter, lint_issues = _run_lint_phase(args, root)
    all_issues.extend(lint_issues)

    sec_analyzer, sec_issues = _run_security_phase(args, root)
    all_issues.extend(sec_issues)

    # ── Async LLM Enrichment (Parallel) ──
    if llm and (detector or finder):
        tasks = []
        if detector:
            tasks.append(detector.enrich_with_llm_async(llm))
        if finder:
            tasks.append(finder.enrich_with_llm_async(llm, functions))
        if tasks:
            await asyncio.gather(*tasks)

    # ── Reporting ──
    if detector:
        summary = detector.summary()
        print_smells(detector.smells, summary)
        results["smells"] = summary

    if finder:
        summary = finder.summary()
        print_duplicates(finder.groups, summary)
        results["duplicates"] = summary

    if linter and lint_issues:
        summary = linter.summary(lint_issues)
        print_lint_report(lint_issues, summary)
        results["lint"] = summary

    if sec_analyzer and sec_issues:
        summary = sec_analyzer.summary(sec_issues)
        print_security_report(sec_issues, summary)
        results["security"] = summary

    # ── Unified Grade ──
    grade_info = print_unified_grade(results)
    results["grade"] = grade_info

    return results


async def main_async():
    """Async entry point for X-Ray CLI scanner."""
    args = _parse_args()
    print(BANNER)

    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"Error: {root} is not a directory.")
        sys.exit(1)

    results = await _run_full_scan(root, args)

    # Save Report
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"\n  Report saved to {args.report}")

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
