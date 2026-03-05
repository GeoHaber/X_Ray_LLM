#!/usr/bin/env python3
"""
X_RAY_Claude.py — Smart AI-Powered Code Analyzer (X-Ray 7.0)
=============================================================

Universal code quality scanner combining:
  - AST-based structural analysis (smells, duplicates)
  - Ruff format check (code formatting)
  - Ruff linter (style, imports, hygiene)
  - Bandit security scanner (vulnerabilities)

Usage::

    python X_RAY_Claude.py --path .                     # default: smells + format + lint + security
    python X_RAY_Claude.py --smell                      # code smell detection only
    python X_RAY_Claude.py --duplicates                 # find similar functions
    python X_RAY_Claude.py --format                     # Ruff format check only
    python X_RAY_Claude.py --lint                       # Ruff linter only
    python X_RAY_Claude.py --security                   # Bandit security only
    python X_RAY_Claude.py --full-scan                  # everything (all 5 analyzers)
    python X_RAY_Claude.py --report scan_results.json   # save JSON report
    python X_RAY_Claude.py --rustify                    # rank functions for Rust porting
    python X_RAY_Claude.py --lint --fix                 # lint + auto-apply Ruff fixes
    python X_RAY_Claude.py --fix-smells                 # auto-repair common issues
    python X_RAY_Claude.py --compare prev.json          # show delta vs previous scan
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import asyncio
from pathlib import Path
from typing import List, Tuple

from Core.config import BANNER
from Core.inference import LLMHelper
from Core.ui_bridge import get_bridge

from Analysis.reporting import print_unified_grade  # noqa: F401 — used by external callers
from Core.scan_phases import (
    scan_codebase,
    run_smell_phase,
    run_duplicate_phase,
    run_format_phase,
    run_lint_phase,
    run_security_phase,
    run_rustify_scan,
    run_web_smell_phase,
    run_health_phase,
    run_smell_fix_phase,
    collect_reports,
)

from Core.utils import setup_logger, check_trial_license as _check_trial_license

setup_logger()  # configure logging once — no duplicate basicConfig


# ═══════════════════════════════════════════════════════════════════════════
#  Interactive TUI — responsive, screen-adaptive, with LLM settings
# ═══════════════════════════════════════════════════════════════════════════


def _supports_interactive() -> bool:
    """Check if stdin is a real terminal (not piped)."""
    return hasattr(sys.stdin, "isatty") and sys.stdin.isatty()


def _term_size() -> Tuple[int, int]:
    """(cols, rows) of current terminal."""
    import shutil

    return shutil.get_terminal_size((80, 24))


def _clear_line():
    """Move cursor up and clear the line."""
    print("\033[A\033[K", end="", flush=True)


def _ansi(code: str, text: str) -> str:
    """Wrap text in ANSI escape codes."""
    return f"\033[{code}m{text}\033[0m"


# ── Platform-specific raw key reader ──

_KEY_CHAR_MAP = {
    " ": "space",
    "\r": "enter",
    "\n": "enter",
    "\t": "tab",
    "\x1b": "quit",
}
_KEY_ALPHA_MAP = {"q": "quit", "a": "all", "n": "none", "s": "settings", "h": "help"}
_WIN32_ESC_MAP = {"H": "up", "P": "down", "K": "left", "M": "right"}
_UNIX_ESC_MAP = {"[A": "up", "[B": "down", "[C": "right", "[D": "left"}


def _resolve_char(ch: str) -> str:
    """Map a raw character to a logical key name."""
    return _KEY_CHAR_MAP.get(ch) or _KEY_ALPHA_MAP.get(ch.lower(), "unknown")


def _read_key_win32() -> str:
    """Read a single keypress on Windows."""
    import msvcrt

    ch = msvcrt.getwch()
    if ch in ("\x00", "\xe0"):
        return _WIN32_ESC_MAP.get(msvcrt.getwch(), "unknown")
    return _resolve_char(ch)


def _read_key_unix() -> str:
    """Read a single keypress on Unix/macOS."""
    import tty
    import termios

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            return _UNIX_ESC_MAP.get(sys.stdin.read(2), "unknown")
        return _resolve_char(ch)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _make_key_reader():
    """Return a zero-argument callable that reads a single keypress."""
    return _read_key_win32 if sys.platform == "win32" else _read_key_unix


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

    visible = len(re.sub(r"\033\[[0-9;]*m", "", text))
    inner = w - 4  # 2 border + 2 padding
    if align == "center":
        pad_left = max(0, (inner - visible) // 2)
        pad_right = max(0, inner - visible - pad_left)
    else:
        pad_left = 0
        pad_right = max(0, inner - visible)
    return (
        _ansi("36", "║")
        + " "
        + " " * pad_left
        + text
        + " " * pad_right
        + " "
        + _ansi("36", "║")
    )


# ── Scan option definitions ──

_SCAN_OPTIONS = [
    ("smell", "Code Smells", "🔬", True, "AST-based structural analysis"),
    ("duplicates", "Duplicates", "🔁", False, "Find similar / copy-paste code"),
    ("format", "Format (Ruff)", "📐", True, "Code formatting check"),
    ("lint", "Lint (Ruff)", "✏️", True, "Style, imports, hygiene"),
    ("security", "Security (Bandit)", "🛡️", True, "Vulnerability scanner"),
    ("rustify", "Rust Score", "🦀", False, "Rank functions for Rust porting"),
    ("rustify_exe", "Rustify → EXE", "⚙️", False, "Full transpile + compile pipeline"),
]


def _load_llm_info():
    """Lazy-load LLM manager, hardware info, and model recommendations."""
    try:
        from Core.llm_manager import LLMManager, recommend_models

        mgr = LLMManager()
        mgr.detect_all()
        return mgr, mgr.hw, recommend_models(mgr.hw)
    except Exception:
        return None, None, None


def _render_scan_page(box_w: int, wide: bool, selected: list, cursor: int) -> str:
    """Build the scan-option TUI panel."""
    lines = ["", "  " + _box_top(box_w)]
    title = _ansi("1;97", "X-RAY 5.0") + "  " + _ansi("36", "Interactive Scanner")
    lines.append("  " + _box_line(box_w, title, "center"))
    lines.append("  " + _box_mid(box_w))
    if wide:
        ctrl = (
            _ansi("90", "↑↓")
            + " move  "
            + _ansi("90", "Space")
            + " toggle  "
            + _ansi("90", "Enter")
            + " run  "
            + _ansi("90", "Tab/s")
            + " LLM settings"
        )
    else:
        ctrl = _ansi("90", "↑↓ Space Enter  s=settings  q=quit")
    lines.append("  " + _box_line(box_w, ctrl, "center"))
    lines.append("  " + _box_sep(box_w))
    for i, (key, label, icon, default, desc) in enumerate(_SCAN_OPTIONS):
        mark = _ansi("1;32", "✓") if selected[i] else _ansi("90", "·")
        arrow = _ansi("1;33", "►") + " " if i == cursor else "  "
        text = (
            f"{arrow}[{mark}] {icon} {label:<22} {_ansi('90', desc)}"
            if wide
            else f"{arrow}[{mark}] {label}"
        )
        lines.append("  " + _box_line(box_w, text))
    lines.append("  " + _box_sep(box_w))
    count = sum(selected)
    summary = _ansi("1;97", f"{count}") + _ansi("90", f"/{len(_SCAN_OPTIONS)} selected")
    shortcuts = (
        _ansi("90", "a")
        + "=all  "
        + _ansi("90", "n")
        + "=none  "
        + _ansi("90", "q")
        + "=quit"
    )
    lines.append(
        "  "
        + _box_line(
            box_w, f"{summary}    {shortcuts}" if wide else f"{summary}  {shortcuts}"
        )
    )
    lines.extend(["  " + _box_bot(box_w), ""])
    return "\n".join(lines)


def _render_hw_section(box_w: int, hw) -> List[str]:
    """Hardware profile lines for the settings panel."""
    if not hw:
        return ["  " + _box_line(box_w, _ansi("33", "  detecting hardware..."))]
    avx = _ansi("32", "AVX2 ✓") if hw.avx2 else _ansi("90", "AVX2 ✗")
    gpu = hw.gpu_name if hw.gpu_name != "none" else _ansi("90", "no GPU detected")
    return [
        "  " + _box_line(box_w, _ansi("1;97", "System Profile")),
        "  " + _box_line(box_w, f"  OS:   {hw.os_name} {hw.os_version} ({hw.arch})"),
        "  " + _box_line(box_w, f"  CPU:  {hw.cpu_brand[:40]}"),
        "  " + _box_line(box_w, f"  RAM:  {hw.ram_gb:.0f} GB   Cores: {hw.cpu_cores}"),
        "  " + _box_line(box_w, f"  GPU:  {gpu}"),
        "  " + _box_line(box_w, f"  SIMD: {avx}"),
        "  " + _box_line(box_w, f"  Tier: {hw.tier_label}"),
    ]


def _render_runtime_section(box_w: int, mgr) -> List[str]:
    """llama.cpp runtime status lines."""
    if not (mgr and mgr.runtime):
        return ["  " + _box_line(box_w, _ansi("90", "  (runtime detection...)"))]
    rt = mgr.runtime
    lines = ["  " + _box_line(box_w, _ansi("1;97", "llama.cpp Runtime"))]
    if rt.installed:
        status = _ansi("32", "✓ installed") + f"  {rt.version}  [{rt.backend}]"
        srv = (
            _ansi("32", f"running :{rt.server_port}")
            if rt.server_running
            else _ansi("90", "stopped")
        )
        lines.append("  " + _box_line(box_w, f"  Status: {status}"))
        lines.append("  " + _box_line(box_w, f"  Server: {srv}"))
    else:
        lines.append("  " + _box_line(box_w, _ansi("33", "  ⚠ llama.cpp not found")))
        lines.append(
            "  "
            + _box_line(box_w, _ansi("90", "  Install: github.com/ggerganov/llama.cpp"))
        )
    return lines


def _render_model_section(box_w: int, wide: bool, models) -> List[str]:
    """Recommended model lines."""
    lines = ["  " + _box_line(box_w, _ansi("1;97", "Recommended Models"))]
    if not models:
        lines.append(
            "  " + _box_line(box_w, _ansi("90", "  (no models fit this hardware)"))
        )
        return lines
    for i, m in enumerate(models[:4], 1):
        tag = _ansi("1;33", " ★ BEST") if i == 1 else ""
        lines.append(
            "  "
            + _box_line(
                box_w, f"  {i}. {m.name}" + (f" ({m.params})" if wide else "") + tag
            )
        )
        if wide:
            det = (
                f"     {m.speed}  Code: {m.code_quality}  RAM: {m.ram_needed_gb:.0f}GB"
            )
            lines.append("  " + _box_line(box_w, _ansi("90", det)))
    return lines


def _render_settings_page(box_w: int, wide: bool, mgr, hw, models) -> str:
    """Build the LLM / hardware settings TUI panel."""
    lines = ["", "  " + _box_top(box_w)]
    title = _ansi("1;97", "LLM & Runtime") + "  " + _ansi("36", "Settings")
    lines.append("  " + _box_line(box_w, title, "center"))
    lines.append("  " + _box_mid(box_w))
    ctrl = (
        _ansi("90", "Tab/Esc") + " back to scan  " + _ansi("90", "Enter") + " confirm"
    )
    lines.append("  " + _box_line(box_w, ctrl, "center"))
    lines.append("  " + _box_sep(box_w))
    lines.extend(_render_hw_section(box_w, hw))
    lines.append("  " + _box_sep(box_w))
    lines.extend(_render_runtime_section(box_w, mgr))
    lines.append("  " + _box_sep(box_w))
    lines.extend(_render_model_section(box_w, wide, models))
    lines.extend(["  " + _box_bot(box_w), ""])
    return "\n".join(lines)


_SCAN_KEY_ACTIONS = {
    "up": lambda c, s: ((c - 1) % len(_SCAN_OPTIONS), s),
    "down": lambda c, s: ((c + 1) % len(_SCAN_OPTIONS), s),
    "space": lambda c, s: (_toggle_at(c, s), s)[1:] and (c, s),
    "all": lambda c, s: (c, [True] * len(_SCAN_OPTIONS)),
    "none": lambda c, s: (c, [False] * len(_SCAN_OPTIONS)),
}


def _toggle_at(idx, selected):
    selected[idx] = not selected[idx]


def _handle_scan_key(key, cursor, selected, page_ref):
    """Handle a keypress on the scan page. Returns (cursor, selected, page, done)."""
    if key == "enter":
        return cursor, selected, "scan", True
    if key in ("tab", "settings"):
        return cursor, selected, "settings", False
    if key == "quit":
        print("\n  Cancelled.")
        sys.exit(0)
    if key == "space":
        selected[cursor] = not selected[cursor]
        return cursor, selected, "scan", False
    action = _SCAN_KEY_ACTIONS.get(key)
    if action:
        cursor, selected = action(cursor, selected)
    return cursor, selected, "scan", False


def _handle_settings_key(key: str) -> str:
    """Handle a keypress while on the settings page. Returns new page name."""
    if key in ("tab", "quit", "settings", "enter"):
        return "scan"
    return "settings"


def _interactive_menu() -> dict:
    """Responsive interactive TUI with scan options + LLM settings.

    Navigation:
      ↑↓ move  |  Space toggle  |  Enter run  |  Tab → LLM settings
      a = all   |  n = none      |  s = settings  |  q = quit
    """
    cols, _rows = _term_size()
    wide = cols >= 80
    box_w = min(cols - 4, 72) if wide else min(cols - 2, 50)
    read_key = _make_key_reader()

    selected = [d for _, _, _, d, _ in _SCAN_OPTIONS]
    cursor = 0
    page = "scan"
    mgr = hw = models = None

    def _draw(content: str) -> int:
        print(content, end="", flush=True)
        return content.count("\n") + 1

    display = _render_scan_page(box_w, wide, selected, cursor)
    line_count = _draw(display)

    while True:
        key = read_key()
        if page == "scan":
            cursor, selected, page, done = _handle_scan_key(key, cursor, selected, page)
            if done:
                break
            if page == "settings" and mgr is None:
                mgr, hw, models = _load_llm_info()
        else:
            page = _handle_settings_key(key)
            if page == "settings":
                continue
        for _ in range(line_count):
            _clear_line()
        display = (
            _render_settings_page(box_w, wide, mgr, hw, models)
            if page == "settings"
            else _render_scan_page(box_w, wide, selected, cursor)
        )
        line_count = _draw(display)

    print()
    return {k: selected[i] for i, (k, _, _, _, _) in enumerate(_SCAN_OPTIONS)}


# scan_codebase imported from Core.scan_phases


# Reporting functions moved to Analysis.reporting


def _handle_system_info(args):
    """Print hardware profile and exit if --system-info."""
    if not args.system_info:
        return
    from Core.llm_manager import LLMManager

    mgr = LLMManager()
    mgr.detect_all()
    print(mgr.format_system_profile())
    print(mgr.format_runtime_status())
    print(mgr.format_model_recommendations())
    sys.exit(0)


def _handle_llm_settings(args):
    """Print LLM settings and exit if --llm-settings."""
    if not args.llm_settings:
        return
    from Core.llm_manager import LLMManager

    mgr = LLMManager(project_dir=Path(args.path).resolve())
    mgr.detect_all()
    print(mgr.format_system_profile())
    print(mgr.format_runtime_status())
    print(mgr.format_model_recommendations())
    status = mgr.check_and_prompt()
    if status.get("needs_install"):
        print("  💡 To install llama.cpp:")
        print("     https://github.com/ggerganov/llama.cpp/releases")
    if status.get("needs_upgrade"):
        print(f"  💡 Newer version available: {status['latest_version']}")
    sys.exit(0)


def _parse_args() -> argparse.Namespace:
    """Parse and normalise CLI arguments."""
    from Core.cli_args import add_common_scan_args, normalize_scan_args

    parser = argparse.ArgumentParser(
        description=BANNER,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_common_scan_args(parser)
    # x_ray_claude-specific flags
    parser.add_argument(
        "--rustify-exe",
        action="store_true",
        help="Full pipeline: scan → optimize → transpile → compile to executable",
    )
    parser.add_argument("--use-llm", action="store_true", help="Enable LLM enrichment")
    parser.add_argument(
        "--llm-settings",
        action="store_true",
        help="Show LLM settings: hardware detection, model recommendations",
    )
    parser.add_argument(
        "--system-info", action="store_true", help="Print hardware profile and exit"
    )
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Launch interactive TUI to select scope and options",
    )
    args = parser.parse_args()

    _handle_system_info(args)
    _handle_llm_settings(args)

    if args.interactive and _supports_interactive():
        choices = _interactive_menu()
        for k in (
            "smell",
            "duplicates",
            "format",
            "lint",
            "security",
            "rustify",
            "rustify_exe",
        ):
            setattr(args, k, choices.get(k, False))
        return args

    normalize_scan_args(args, extra_flags=("rustify_exe",))
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
    functions, classes, errors = scan_codebase(root, exclude=args.exclude, verbose=True)
    duration = time.time() - start
    print(
        f"  Scanned {len(functions)} functions, {len(classes)} classes in {duration:.2f}s"
    )
    return functions, classes, errors


def _run_smell_phase(args, functions, classes):
    """Run AST smell detection if requested."""
    if not args.smell:
        return None, []
    return run_smell_phase(functions, classes)


def _run_duplicate_phase(args, functions):
    """Run duplicate detection if requested."""
    if not args.duplicates:
        return None
    return run_duplicate_phase(functions)


def _run_format_phase(args, root):
    """Run Ruff format check if requested."""
    if not args.format:
        return None, []
    return run_format_phase(root, exclude=args.exclude)


def _run_lint_phase(args, root):
    """Run Ruff lint analysis (and optionally auto-fix) if requested."""
    if not args.lint:
        return None, []
    linter, issues = run_lint_phase(root, exclude=args.exclude)
    if getattr(args, "fix", False) and linter is not None:
        n_fixed = linter.fix(root, exclude=args.exclude)
        if n_fixed:
            print(f"  ✔ Ruff auto-fix applied {n_fixed} issue(s)")
        else:
            print("  ℹ No auto-fixable Ruff issues found")
    return linter, issues


def _run_security_phase(args, root):
    """Run Bandit security analysis if requested."""
    if not args.security:
        return None, []
    return run_security_phase(root, exclude=args.exclude)


def _run_web_phase(args, root):
    """Run JS/TS/React web smell detection if requested."""
    if not getattr(args, "web", False):
        return None
    detector, smells = run_web_smell_phase(root, exclude=args.exclude)
    return detector


def _run_health_phase(args, root):
    """Run project health check if requested."""
    if not getattr(args, "health", False):
        return None
    auto_fix = getattr(args, "fix_smells", False)
    return run_health_phase(root, auto_fix=auto_fix)


def _run_fix_smells_phase(args, root):
    """Run auto-fix smell engine if requested."""
    if not getattr(args, "fix_smells", False):
        return None
    result = run_smell_fix_phase(root, exclude=args.exclude)
    bridge = get_bridge()
    if result.fixes_applied:
        bridge.log(f"\n  ✔ Auto-Fix Applied: {result.fixes_applied} fix(es)")
        if result.console_logs_commented:
            bridge.log(f"    - {result.console_logs_commented} console.log(s) commented out")
        if result.prints_commented:
            bridge.log(f"    - {result.prints_commented} debug print(s) commented out")
        if result.project_files_created:
            bridge.log(f"    - Created: {', '.join(result.project_files_created)}")
    else:
        bridge.log("  ℹ No auto-fixable smells found")
    return result


def _run_rustify(root: Path, args: argparse.Namespace) -> dict:
    """Rank functions by Rust-porting suitability and print results."""
    return run_rustify_scan(root, exclude=args.exclude)


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
        bar = "█" * filled + "░" * (bar_len - filled)
        print(f"\r  [{bar}] {frac * 100:5.1f}% {label:<40}", end="", flush=True)

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
    print(
        f"  Scanned:    {report.candidates_total} functions in {report.scan_duration_s}s"
    )
    print(f"  Selected:   {report.candidates_selected} candidates (score ≥ 3.0)")

    for phase in report.phases:
        status = phase.get("status", "unknown")
        name = phase.get("name", "")
        icon = "✅" if status == "ok" else "❌" if status == "failed" else "⚠️"
        print(f"  {icon} {name}: {status}")
        if "artefact" in phase and phase["artefact"]:
            print(f"     → Executable: {phase['artefact']}")

    if report.compile_result and report.compile_result.success:
        exe = report.compile_result.artefact_path
        print(f"\n  \033[1;32m✓ SUCCESS\033[0m — Executable built: {exe}")
        print(f"  Run it:  {exe} --help")
    elif report.errors:
        print("\n  \033[1;31m✗ ERRORS:\033[0m")
        for err in report.errors[:5]:
            print(f"    {err[:200]}")

    return {"rustify_exe": report.to_dict()}


# collect_reports imported from Core.scan_phases


async def _run_full_scan(root: Path, args: argparse.Namespace) -> dict:
    """Execute all requested scan phases and return the results dict."""
    # ── Rustify modes ──
    if args.rustify_exe:
        return _run_rustify_exe(root, args)
    if args.rustify:
        return _run_rustify(root, args)

    llm = _init_llm(args, root)
    functions, classes, errors = _scan_codebase_phase(root, args)

    all_issues = []

    detector, smells = _run_smell_phase(args, functions, classes)
    all_issues.extend(smells)

    finder = _run_duplicate_phase(args, functions)

    fmt_analyzer, format_issues = _run_format_phase(args, root)
    all_issues.extend(format_issues)

    linter, lint_issues = _run_lint_phase(args, root)
    all_issues.extend(lint_issues)

    sec_analyzer, sec_issues = _run_security_phase(args, root)
    all_issues.extend(sec_issues)

    # ── New v7.0 phases ──
    web_detector = _run_web_phase(args, root)
    health_analyzer = _run_health_phase(args, root)

    # ── Auto-fix smells (--fix-smells) ──
    _run_fix_smells_phase(args, root)

    # ── Test generation (--gen-tests) ──
    if getattr(args, "gen_tests", False):
        from Core.scan_phases import run_test_gen_phase
        # Collect JS analyses from web_detector if present
        js_analyses = None
        if web_detector and hasattr(web_detector, "_analyses"):
            js_analyses = web_detector._analyses
        health_checks = None
        if health_analyzer and hasattr(health_analyzer, "report") and health_analyzer.report:
            health_checks = health_analyzer.report.checks
        test_output = Path(getattr(args, "test_output", ".")).resolve()
        test_report = run_test_gen_phase(
            root,
            functions=functions,
            classes=classes,
            smells=all_issues,
            js_analyses=js_analyses,
            health_checks=health_checks,
            output_dir=test_output,
        )
        bridge = get_bridge()
        bridge.log(f"\n  {'='*60}")
        bridge.log(f"  🧪 MONKEY TESTS GENERATED")
        bridge.log(f"     Files: {len(test_report.files_created)}")
        bridge.log(f"     Tests: {test_report.total_tests}")
        bridge.log(f"     Languages: {', '.join(test_report.languages)}")
        bridge.log(f"     Output: {test_output}")
        bridge.log(f"  {'='*60}")

    # ── Async LLM Enrichment (Parallel) ──
    if llm and (detector or finder):
        tasks = []
        if detector:
            tasks.append(detector.enrich_with_llm_async(llm))
        if finder:
            from Analysis.duplicates import enrich_with_llm_async as _dup_enrich

            tasks.append(_dup_enrich(finder, llm, functions))
        if tasks:
            await asyncio.gather(*tasks)

    from Core.scan_phases import AnalysisComponents

    return collect_reports(
        AnalysisComponents(
            detector,
            finder,
            fmt_analyzer,
            format_issues,
            linter,
            lint_issues,
            sec_analyzer,
            sec_issues,
        )
    )


async def main_async():
    """Async entry point for X-Ray CLI scanner."""
    args = _parse_args()
    print(BANNER)

    # --- Trial license gate ---
    if not _check_trial_license():
        sys.exit(1)

    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"Error: {root} is not a directory.")
        sys.exit(1)

    # Load previous scan for trend comparison (--compare)
    prev_results = None
    compare_path = getattr(args, "compare", None)
    if compare_path:
        from Analysis.trend import load_prev_results
        prev_results = load_prev_results(compare_path)
        if prev_results is None:
            print(f"  [!] --compare: could not read '{compare_path}' — trend disabled")

    results = await _run_full_scan(root, args)

    # Print trend delta if available (injected into print_unified_grade via results key)
    if prev_results and "grade" in results:
        from Analysis.reporting import print_unified_grade as _pug
        from Analysis.trend import compare_scans, format_grade_delta
        delta = compare_scans(prev_results, results)
        delta_line = format_grade_delta(delta)
        if delta_line:
            print(f"  {delta_line}")
        results.setdefault("grade", {}).update({"delta": delta})

    # Save Report
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"\n  Report saved to {args.report}")


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
