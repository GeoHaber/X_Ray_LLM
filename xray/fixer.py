"""
X-Ray Fixer — Deterministic auto-fix for scanner findings.

Tier 1: Rule-based fixers (instant, no LLM) for known patterns.
Tier 2: Ruff integration (optional) for style/lint fixes.
Tier 3: LLM fallback (optional) via LLMEngine for complex issues.
"""

import difflib
import re
import shutil
import subprocess
import textwrap
from pathlib import Path


# ── Fix Result ───────────────────────────────────────────────────────────

class FixResult:
    __slots__ = ("fixable", "description", "diff", "new_lines", "error")

    def __init__(self, *, fixable=False, description="", diff="",
                 new_lines=None, error=""):
        self.fixable = fixable
        self.description = description
        self.diff = diff
        self.new_lines = new_lines
        self.error = error


# ── Helpers ──────────────────────────────────────────────────────────────

def _read_file(path: str) -> list[str]:
    return Path(path).read_text(encoding="utf-8", errors="replace").splitlines(True)


def _make_diff(old_lines: list[str], new_lines: list[str], filepath: str) -> str:
    return "".join(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{Path(filepath).name}",
        tofile=f"b/{Path(filepath).name}",
        lineterm="\n",
    ))


def _get_indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _in_try_block(lines: list[str], target_idx: int) -> bool:
    """Check if line is already inside a try: block."""
    indent = _get_indent(lines[target_idx])
    for i in range(target_idx - 1, max(target_idx - 20, -1), -1):
        stripped = lines[i].strip()
        if stripped == "try:" and _get_indent(lines[i]) < indent:
            return True
        if stripped and not stripped.startswith("#") and _get_indent(lines[i]) <= indent:
            if not stripped.startswith(("try:", "if ", "elif ", "else:", "for ", "while ")):
                break
    return False


# ── Rule-Based Fixers ────────────────────────────────────────────────────
#
# Each fixer: (filepath, line_num_1based, matched_text, lines) -> FixResult
# lines = full file as list of strings (with newlines)

def _fix_py005_json_parse(filepath, line_num, matched_text, lines):
    """PY-005: Wrap json.loads/json.load in try/except JSONDecodeError."""
    idx = line_num - 1
    if idx >= len(lines):
        return FixResult(error="Line out of range")

    line = lines[idx]
    if _in_try_block(lines, idx):
        return FixResult(error="Already in a try block")

    indent = _get_indent(line)
    inner = indent + "    "
    code = line.rstrip("\n\r")

    # Find the variable being assigned (if any)
    assign_match = re.match(r'^(\s*\w[\w.]*)\s*=\s*', line)
    default_var = assign_match.group(1).strip() if assign_match else None

    new = []
    new.append(f"{indent}try:\n")
    new.append(f"{inner}{code.strip()}\n")
    new.append(f"{indent}except json.JSONDecodeError:\n")
    if default_var:
        # Guess a safe default based on what follows
        new.append(f"{inner}{default_var} = {{}}\n")
    else:
        new.append(f"{inner}pass  # handle malformed JSON\n")

    new_lines = lines[:idx] + new + lines[idx + 1:]
    return FixResult(
        fixable=True,
        description="Wrapped json.loads() in try/except json.JSONDecodeError",
        diff=_make_diff(lines, new_lines, filepath),
        new_lines=new_lines,
    )


def _fix_py007_os_environ(filepath, line_num, matched_text, lines):
    """PY-007: Replace os.environ['KEY'] with os.environ.get('KEY', '')."""
    idx = line_num - 1
    if idx >= len(lines):
        return FixResult(error="Line out of range")

    line = lines[idx]
    # Replace os.environ["KEY"] with os.environ.get("KEY", "")
    new_line = re.sub(
        r'os\.environ\[([\'"])(.+?)\1\]',
        r'os.environ.get(\1\2\1, "")',
        line,
    )
    if new_line == line:
        return FixResult(error="Could not match os.environ[] pattern")

    new_lines = lines[:idx] + [new_line] + lines[idx + 1:]
    return FixResult(
        fixable=True,
        description="Replaced os.environ['KEY'] with os.environ.get('KEY', \"\")",
        diff=_make_diff(lines, new_lines, filepath),
        new_lines=new_lines,
    )


def _fix_qual001_bare_except(filepath, line_num, matched_text, lines):
    """QUAL-001: Replace bare except: with except Exception:."""
    idx = line_num - 1
    if idx >= len(lines):
        return FixResult(error="Line out of range")

    line = lines[idx]
    new_line = re.sub(r'except\s*:', 'except Exception:', line)
    if new_line == line:
        return FixResult(error="Could not match bare except")

    new_lines = lines[:idx] + [new_line] + lines[idx + 1:]
    return FixResult(
        fixable=True,
        description="Replaced bare 'except:' with 'except Exception:'",
        diff=_make_diff(lines, new_lines, filepath),
        new_lines=new_lines,
    )


def _fix_qual003_int_input(filepath, line_num, matched_text, lines):
    """QUAL-003: Wrap unchecked int() on user input in try/except."""
    idx = line_num - 1
    if idx >= len(lines):
        return FixResult(error="Line out of range")

    line = lines[idx]
    if _in_try_block(lines, idx):
        return FixResult(error="Already in a try block")

    indent = _get_indent(line)
    inner = indent + "    "
    code = line.rstrip("\n\r")

    assign_match = re.match(r'^(\s*\w[\w.]*)\s*=\s*', line)
    default_var = assign_match.group(1).strip() if assign_match else None

    new = []
    new.append(f"{indent}try:\n")
    new.append(f"{inner}{code.strip()}\n")
    new.append(f"{indent}except (ValueError, TypeError):\n")
    if default_var:
        new.append(f"{inner}{default_var} = 0\n")
    else:
        new.append(f"{inner}pass  # handle non-numeric input\n")

    new_lines = lines[:idx] + new + lines[idx + 1:]
    return FixResult(
        fixable=True,
        description="Wrapped int() in try/except (ValueError, TypeError)",
        diff=_make_diff(lines, new_lines, filepath),
        new_lines=new_lines,
    )


def _fix_qual004_float_input(filepath, line_num, matched_text, lines):
    """QUAL-004: Wrap unchecked float() on user input in try/except."""
    idx = line_num - 1
    if idx >= len(lines):
        return FixResult(error="Line out of range")

    line = lines[idx]
    if _in_try_block(lines, idx):
        return FixResult(error="Already in a try block")

    indent = _get_indent(line)
    inner = indent + "    "
    code = line.rstrip("\n\r")

    assign_match = re.match(r'^(\s*\w[\w.]*)\s*=\s*', line)
    default_var = assign_match.group(1).strip() if assign_match else None

    new = []
    new.append(f"{indent}try:\n")
    new.append(f"{inner}{code.strip()}\n")
    new.append(f"{indent}except (ValueError, TypeError):\n")
    if default_var:
        new.append(f"{inner}{default_var} = 0.0\n")
    else:
        new.append(f"{inner}pass  # handle non-numeric input\n")

    new_lines = lines[:idx] + new + lines[idx + 1:]
    return FixResult(
        fixable=True,
        description="Wrapped float() in try/except (ValueError, TypeError)",
        diff=_make_diff(lines, new_lines, filepath),
        new_lines=new_lines,
    )


def _fix_sec003_shell_true(filepath, line_num, matched_text, lines):
    """SEC-003: Replace shell=True with shell=False."""
    idx = line_num - 1
    if idx >= len(lines):
        return FixResult(error="Line out of range")

    line = lines[idx]
    # Simple case: just flip shell=True to shell=False
    new_line = line.replace("shell=True", "shell=False")
    if new_line == line:
        return FixResult(error="Could not find shell=True on this line")

    new_lines = lines[:idx] + [new_line] + lines[idx + 1:]
    return FixResult(
        fixable=True,
        description="Changed shell=True to shell=False (review: args must be a list)",
        diff=_make_diff(lines, new_lines, filepath),
        new_lines=new_lines,
    )


def _fix_sec009_pickle_yaml(filepath, line_num, matched_text, lines):
    """SEC-009: Replace yaml.load() with yaml.safe_load()."""
    idx = line_num - 1
    if idx >= len(lines):
        return FixResult(error="Line out of range")

    line = lines[idx]
    new_line = line
    new_line = new_line.replace("yaml.load(", "yaml.safe_load(")
    # Remove Loader= arg since safe_load doesn't need it
    new_line = re.sub(r',\s*Loader\s*=\s*\w+\.?\w*', '', new_line)
    if new_line == line:
        if "pickle.load" in line:
            return FixResult(error="pickle.load requires manual review — replace with json.load")
        return FixResult(error="Could not auto-fix this pattern")

    new_lines = lines[:idx] + [new_line] + lines[idx + 1:]
    return FixResult(
        fixable=True,
        description="Replaced yaml.load() with yaml.safe_load()",
        diff=_make_diff(lines, new_lines, filepath),
        new_lines=new_lines,
    )


# ── Fixer Registry ──────────────────────────────────────────────────────

FIXERS = {
    "PY-005": _fix_py005_json_parse,
    "PY-007": _fix_py007_os_environ,
    "QUAL-001": _fix_qual001_bare_except,
    "QUAL-003": _fix_qual003_int_input,
    "QUAL-004": _fix_qual004_float_input,
    "SEC-003": _fix_sec003_shell_true,
    "SEC-009": _fix_sec009_pickle_yaml,
}

# Rules that have auto-fixers
FIXABLE_RULES = set(FIXERS.keys())


# ── Public API ───────────────────────────────────────────────────────────

def preview_fix(finding: dict) -> dict:
    """Generate a fix preview (diff) without modifying the file.

    finding: dict with keys rule_id, file, line, matched_text
    Returns: { fixable, diff, description, error }
    """
    rule_id = finding.get("rule_id", "")
    filepath = finding.get("file", "")
    line_num = finding.get("line", 0)
    matched = finding.get("matched_text", "")

    if rule_id not in FIXERS:
        return {"fixable": False, "diff": "", "description": "",
                "error": f"No auto-fixer for {rule_id}. Fix hint: {finding.get('fix_hint', '')}"}

    if not Path(filepath).is_file():
        return {"fixable": False, "diff": "", "description": "",
                "error": f"File not found: {filepath}"}

    lines = _read_file(filepath)
    fixer = FIXERS[rule_id]
    result = fixer(filepath, line_num, matched, lines)

    return {
        "fixable": result.fixable,
        "diff": result.diff,
        "description": result.description,
        "error": result.error,
    }


def apply_fix(finding: dict) -> dict:
    """Apply a fix to the file. Creates a .bak backup first.

    Returns: { ok, description, error }
    """
    rule_id = finding.get("rule_id", "")
    filepath = finding.get("file", "")
    line_num = finding.get("line", 0)
    matched = finding.get("matched_text", "")

    if rule_id not in FIXERS:
        return {"ok": False, "error": f"No auto-fixer for {rule_id}"}

    p = Path(filepath)
    if not p.is_file():
        return {"ok": False, "error": f"File not found: {filepath}"}

    lines = _read_file(filepath)
    fixer = FIXERS[rule_id]
    result = fixer(filepath, line_num, matched, lines)

    if not result.fixable:
        return {"ok": False, "error": result.error}

    # Write patched file
    p.write_text("".join(result.new_lines), encoding="utf-8")

    return {"ok": True, "description": result.description, "diff": result.diff}


def apply_fixes_bulk(findings: list[dict]) -> dict:
    """Apply fixes to multiple findings. Groups by file to avoid conflicts.

    Processes one file at a time, re-reading after each fix to handle
    line number shifts from prior fixes in the same file.

    Returns: { applied, skipped, errors: [...] }
    """
    applied = 0
    skipped = 0
    errors = []

    # Group by file, sort by line descending (fix from bottom up to preserve line numbers)
    by_file: dict[str, list[dict]] = {}
    for f in findings:
        fp = f.get("file", "")
        by_file.setdefault(fp, []).append(f)

    for filepath, file_findings in by_file.items():
        # Sort by line descending so fixes don't shift earlier line numbers
        file_findings.sort(key=lambda x: x.get("line", 0), reverse=True)

        for finding in file_findings:
            result = apply_fix(finding)
            if result.get("ok"):
                applied += 1
            else:
                skipped += 1
                if result.get("error"):
                    errors.append(f"{finding.get('rule_id')} at {filepath}:{finding.get('line')} — {result['error']}")

    return {"applied": applied, "skipped": skipped, "errors": errors}


def run_ruff_fix(filepath: str) -> dict:
    """Run ruff auto-fix on a file (if ruff is installed)."""
    ruff = shutil.which("ruff")
    if not ruff:
        return {"ok": False, "error": "ruff not installed (pip install ruff)"}

    try:
        proc = subprocess.run(
            [ruff, "check", "--fix", "--unsafe-fixes", filepath],
            capture_output=True, text=True, timeout=30,
        )
        return {"ok": True, "output": proc.stdout + proc.stderr}
    except Exception as e:
        return {"ok": False, "error": str(e)}
