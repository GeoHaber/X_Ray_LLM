"""
Chat Engine — knowledge-based chat bot for the X-Ray UI.

Extracted from ui_server.py.
"""

import re as _re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_FIX_MARK = " \u2705fix"

_GUIDE_TEXT = ""


def load_guide():
    """Load X_RAY_LLM_GUIDE.md once at startup for chat context."""
    global _GUIDE_TEXT
    guide_path = ROOT / "X_RAY_LLM_GUIDE.md"
    if guide_path.exists():
        _GUIDE_TEXT = guide_path.read_text(encoding="utf-8", errors="ignore")


# Rule knowledge base
_RULES = {
    # Security (14)
    "SEC-001": ("XSS: Template literal in innerHTML", "HIGH", False),
    "SEC-002": ("XSS: String concat to innerHTML", "HIGH", False),
    "SEC-003": ("Command injection: shell=True", "HIGH", True),
    "SEC-004": ("SQL injection: Query formatting", "HIGH", False),
    "SEC-005": ("SSRF: URL from user input", "MEDIUM", False),
    "SEC-006": ("CORS misconfiguration: wildcard", "MEDIUM", False),
    "SEC-007": ("Code injection: eval/exec", "HIGH", False),
    "SEC-008": ("Hardcoded secret", "MEDIUM", False),
    "SEC-009": ("Unsafe deserialization", "HIGH", True),
    "SEC-010": ("Path traversal", "MEDIUM", False),
    "SEC-011": ("Timing attack: == on secrets", "MEDIUM", False),
    "SEC-012": ("Debug mode enabled in production", "HIGH", False),
    "SEC-013": ("Weak hash algorithm: MD5/SHA1", "MEDIUM", False),
    "SEC-014": ("TLS verification disabled", "HIGH", False),
    # Quality (13)
    "QUAL-001": ("Bare except clause", "MEDIUM", True),
    "QUAL-002": ("Silent exception swallowing", "LOW", False),
    "QUAL-003": ("Unchecked int() on user input", "MEDIUM", True),
    "QUAL-004": ("Unchecked float() on user input", "MEDIUM", True),
    "QUAL-005": (".items() on possibly-None return", "LOW", False),
    "QUAL-006": ("Non-daemon threads", "MEDIUM", False),
    "QUAL-007": ("TODO/FIXME markers", "LOW", False),
    "QUAL-008": ("Long sleep (10+ seconds)", "MEDIUM", False),
    "QUAL-009": ("Keep-alive header in HTTP", "HIGH", False),
    "QUAL-010": ("localStorage without try/catch", "MEDIUM", False),
    "QUAL-011": ("Broad Exception catching", "MEDIUM", False),
    "QUAL-012": ("String concatenation in loop", "LOW", False),
    "QUAL-013": ("Line exceeds 200 characters", "LOW", False),
    # Python (11)
    "PY-001": ("Return type mismatch", "MEDIUM", False),
    "PY-002": (".items() on method returning None", "HIGH", False),
    "PY-003": ("Wildcard import", "MEDIUM", False),
    "PY-004": ("print() debug statement", "LOW", False),
    "PY-005": ("JSON without error handling", "HIGH", True),
    "PY-006": ("Global mutation", "MEDIUM", False),
    "PY-007": ("os.envir" + "on[] crashes on missing", "MEDIUM", True),
    "PY-008": ("open() without encoding", "MEDIUM", False),
    "PY-009": ("Captured but ignored exception", "MEDIUM", False),
    "PY-010": ("sys.exit() in library code", "MEDIUM", False),
    "PY-011": ("Long isinstance chain", "LOW", False),
}

_TOOLS_LIST = [
    "Dead Code", "Code Smells", "Duplicates", "Formatting (ruff)",
    "Type Check (pyright)", "Bandit (security)", "Ruff --fix",
    "Import Graph", "Git Hotspots", "Project Health",
    "SATD (tech debt)", "Release Readiness",
    "AI-Generated Code Detection", "Web Smells",
    "Test Stub Generator", "Remediation Time Estimate",
    "Circular Call Detection", "Module Coupling & Cohesion",
    "Unused Imports",
]

_PM_FEATURES = {
    "risk heatmap": "Color-coded grid of files by risk score \u2014 red = urgent, green = clean. Uses findings severity \u00d7 density.",
    "module cards": "Per-directory grade cards (A+ through F) showing issue breakdown for each module.",
    "confidence meter": "Large percentage showing release confidence based on quality gate thresholds.",
    "sprint batches": "Groups findings into 4 work packages: Critical, Security, Quality, Cleanup \u2014 ready for sprint planning.",
    "architecture map": "Visualizes project layers (API, core, utils, tests) with dependency arrows.",
    "call graph": "Interactive vis.js graph of function call relationships \u2014 shows entry points, leaves, and call chains.",
    "circular calls": "Detects function-level circular call chains (macaroni code), recursive functions, and hub functions with high fan-in \u00d7 fan-out.",
    "coupling": "Per-module afferent/efferent coupling, instability metric (I=Ce/(Ca+Ce)), cohesion estimate, and health classification (healthy/god/fragile/isolated).",
    "unused imports": "AST-based detection of imported names never referenced anywhere in the file \u2014 dead imports that clutter code.",
}


def chat_reply(message: str, context: dict) -> str:
    """Generate a knowledge-based reply about X-Ray features."""
    lo = message.lower().strip()

    # Direct rule lookup
    for rule_id, (name, severity, fixable) in _RULES.items():
        if rule_id.lower() in lo:
            fix_str = "\u2705 Auto-fixable" if fixable else "\u274c No auto-fix (manual or LLM)"
            return f"<strong>{rule_id}: {name}</strong><br>Severity: <strong>{severity}</strong><br>Fix: {fix_str}"

    # PM Dashboard features
    for feature, desc in _PM_FEATURES.items():
        if feature in lo or feature.replace(" ", "") in lo.replace(" ", ""):
            return f"<strong>{feature.title()}</strong>: {desc}"

    if _re.search(r"\brule|all rule|38 rule|28 rule|list rule", lo):
        sec = [f"<strong>{k}</strong>: {v[0]} ({v[1]})" for k, v in _RULES.items() if k.startswith("SEC")]
        qual = [f"<strong>{k}</strong>: {v[0]} ({v[1]})" for k, v in _RULES.items() if k.startswith("QUAL")]
        py = [f"<strong>{k}</strong>: {v[0]} ({v[1]})" for k, v in _RULES.items() if k.startswith("PY")]
        return (
            "<strong>38 Scan Rules:</strong><br><br>"
            "<strong>Security (14):</strong><br>" + "<br>".join(sec)
            + "<br><br><strong>Quality (13):</strong><br>" + "<br>".join(qual)
            + "<br><br><strong>Python (11):</strong><br>" + "<br>".join(py)
        )

    if _re.search(r"\bfix|auto.?fix|fixable|fixer", lo):
        fixable = [f"<strong>{k}</strong>: {v[0]}" for k, v in _RULES.items() if v[2]]
        return (
            "<strong>7 Auto-Fixable Rules</strong> (no LLM needed):<br>"
            + "<br>".join(fixable)
            + "<br><br>Click the \U0001f527 wrench icon on any finding, or use <code>/api/apply-fix</code>."
        )

    if _re.search(r"\bpm|dashboard|project.?manag", lo):
        items = [f"\u2022 <strong>{k.title()}</strong>: {v}" for k, v in _PM_FEATURES.items()]
        return "<strong>PM Dashboard \u2014 9 Features:</strong><br><br>" + "<br>".join(items)

    if _re.search(r"\btool|analys|analyzer", lo):
        numbered = [f"{i + 1}. {t}" for i, t in enumerate(_TOOLS_LIST)]
        return "<strong>19 Analysis Tools:</strong><br>" + "<br>".join(numbered)

    if _re.search(r"\bscan|how.*start|begin|quick.?start", lo):
        return (
            "<strong>How to Scan:</strong><br>"
            "1. Browse to a directory in the left sidebar<br>"
            "2. Choose engine (Python or Rust) and severity filter<br>"
            "3. Click <strong>Scan Project</strong><br>"
            "4. Results appear on the right with severity badges<br><br>"
            "CLI: <code>python -m xray.agent /path --dry-run</code>"
        )

    if _re.search(r"\bgrade|score|letter|a\+|rating", lo):
        return (
            "<strong>Grading System:</strong><br>"
            "\u2022 A+ = 0 issues<br>\u2022 A = 1\u20133<br>\u2022 B = 4\u20137<br>\u2022 C = 8\u201312<br>"
            "\u2022 D = 13\u201320<br>\u2022 F = 21+<br><br>"
            "Weighted: High\u00d73 + Medium\u00d71 + Low\u00d70.3<br>"
            "Quality Gate in sidebar sets pass/fail thresholds."
        )

    if _re.search(r"\bapi|endpoint|rest|http", lo):
        return (
            "<strong>34+ API Endpoints</strong> on <code>localhost:8077/api/</code>:<br><br>"
            "Core: <code>/api/scan</code> (SSE), <code>/api/browse</code>, <code>/api/info</code>, <code>/api/abort</code><br>"
            "Fix: <code>/api/preview-fix</code>, <code>/api/apply-fix</code>, <code>/api/apply-fixes-bulk</code><br>"
            "Analysis: <code>/api/dead-code</code>, <code>/api/smells</code>, <code>/api/duplicates</code>, "
            "<code>/api/format</code>, <code>/api/typecheck</code>, <code>/api/bandit</code>, <code>/api/ruff</code><br>"
            "PM: <code>/api/risk-heatmap</code>, <code>/api/module-cards</code>, <code>/api/confidence</code>, "
            "<code>/api/sprint-batches</code>, <code>/api/architecture</code>, <code>/api/call-graph</code><br>"
            "CGC: <code>/api/circular-calls</code>, <code>/api/coupling</code>, <code>/api/unused-imports</code><br>"
            "Utility: <code>/api/chat</code>, <code>/api/project-review</code>"
        )

    if _re.search(r"\brust|engine|fast|performance|speed", lo):
        return (
            "<strong>Dual Engines:</strong><br>"
            "\u2022 <strong>Python</strong>: Cross-platform, always available, full feature set<br>"
            "\u2022 <strong>Rust</strong>: ~10\u00d7 faster, optional. Build: <code>python build.py</code><br><br>"
            "Switch in the sidebar Settings \u2192 Engine dropdown."
        )

    if _re.search(r"\bsecurity|vuln|xss|inject|sql|ssrf|cors|eval|pickle|secret|password", lo):
        sec = [
            f"<strong>{k}</strong>: {v[0]} ({v[1]}){_FIX_MARK if v[2] else ''}"
            for k, v in _RULES.items() if k.startswith("SEC")
        ]
        return "<strong>Security Rules (14):</strong><br>" + "<br>".join(sec)

    if _re.search(r"\bquality|smell|except|magic|dup|long func|param", lo):
        qual = [
            f"<strong>{k}</strong>: {v[0]} ({v[1]}){_FIX_MARK if v[2] else ''}"
            for k, v in _RULES.items() if k.startswith("QUAL")
        ]
        return "<strong>Quality Rules (13):</strong><br>" + "<br>".join(qual)

    if _re.search(r"\bpython rule|py rule|print|assert|wildcard|import\b", lo):
        py = [
            f"<strong>{k}</strong>: {v[0]} ({v[1]}){_FIX_MARK if v[2] else ''}"
            for k, v in _RULES.items() if k.startswith("PY")
        ]
        return "<strong>Python Rules (11):</strong><br>" + "<br>".join(py)

    if _re.search(r"\bhello|hi\b|hey|help|what can you", lo):
        return (
            "Hello! I'm the <strong>X-Ray Assistant</strong>. I can help with:<br><br>"
            "\u2022 <strong>rules</strong> \u2014 all 38 scan rules (14 security + 13 quality + 11 Python)<br>"
            "\u2022 <strong>auto-fix</strong> \u2014 which rules have automatic fixes<br>"
            "\u2022 <strong>tools</strong> \u2014 19 analysis tools<br>"
            "\u2022 <strong>PM Dashboard</strong> \u2014 9 project management features<br>"
            "\u2022 <strong>scanning</strong> \u2014 how to scan a project<br>"
            "\u2022 <strong>grading</strong> \u2014 score and letter grade system<br>"
            "\u2022 <strong>API</strong> \u2014 34+ REST endpoints<br>"
            "\u2022 <strong>engines</strong> \u2014 Python vs Rust<br><br>"
            "Or ask about a specific rule like <code>SEC-003</code>!"
        )

    # Scan context
    has_results = context.get("has_results", False)
    findings = context.get("findings_count", 0)
    if has_results and _re.search(r"\bresult|finding|current|status|summary", lo):
        return (
            f"Current scan: <strong>{findings} findings</strong> in "
            f"<code>{context.get('directory', 'unknown')}</code>. "
            "Use the filter tabs above the results to sort by severity or rule."
        )

    return (
        "I know about X-Ray's <strong>38 rules</strong>, <strong>7 auto-fixers</strong>, "
        "<strong>19 tools</strong>, <strong>9 PM Dashboard features</strong>, <strong>grading</strong>, "
        "and <strong>34+ API endpoints</strong>. "
        "Try asking about any of those, or a specific rule like <code>SEC-003</code>!"
    )
