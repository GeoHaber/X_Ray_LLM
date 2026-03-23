#!/usr/bin/env python3
"""
Pre-Parser / Code Generator: Python Rules → Rust mod.rs

Reads the Python rule definitions (single source of truth) and generates
syntactically-correct Rust code with proper raw string escaping.

Problem solved:
  Python raw strings:  r"['\"]"  → regex sees  ['"]  (match ' or ")
  Rust r"..." can't contain " → must use r#"..."# where \" just becomes "

This script handles ALL the escaping so humans never touch Rust regex strings.

Usage:
  python generate_rust_rules.py              # writes scanner/src/rules/mod.rs
  python generate_rust_rules.py --check      # verify parity, don't write
  python generate_rust_rules.py --dry-run    # print to stdout
"""

import logging
import os
import re
import sys

logger = logging.getLogger(__name__)

# ── Load Python rules (source of truth) ────────────────────────────────────

sys.path.insert(0, os.path.dirname(__file__))
from xray.rules.python_rules import PYTHON_RULES
from xray.rules.quality import QUALITY_RULES
from xray.rules.security import SECURITY_RULES


def python_pattern_to_rust_literal(pattern: str) -> str:
    """Convert a Python raw-string regex pattern to a Rust raw-string literal.

    In Python:  r"['\"]"  → the regex is ['\\"]  (two chars in char class)
    In Rust:    r#"['\"]"# would make \\" be a literal backslash+quote
                BUT in regex, [\\'"] and ['"] mean the same thing.

    Strategy:
      1. If pattern has no double-quote → use r"pattern"     (simple)
      2. If pattern has double-quote   → use r#"pattern"#    (extended)

    For case 2, the pattern stays identical because Python's r"..." and
    Rust's r#"..."# both treat everything literally (no escape processing).
    The only difference is what terminates the string — for Rust r#""#,
    the only forbidden sequence is "#.
    """
    # Check: does the pattern contain a literal double-quote character?
    # In Python raw strings, \" is two chars: backslash + quote
    # Python's r"['\"]" stores the chars: [ ' \ " ]
    # So we check if '"' is in the actual string value
    if '"' in pattern:
        # Use r#"..."# — the pattern goes in verbatim
        # Safety: check it doesn't contain "# which would break r#""#
        if '"#' in pattern:
            # Extremely rare — use r##"..."## syntax
            return f'r##"{pattern}"##'
        return f'r#"{pattern}"#'
    else:
        # Simple r"..." is fine
        return f'r"{pattern}"'


def rust_langs(langs: list[str]) -> str:
    """Format language list as Rust slice literal."""
    items = ", ".join(f'"{lang}"' for lang in langs)
    return f"&[{items}]"


def rust_string(s: str) -> str:
    """Escape a plain string for Rust double-quoted literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def validate_pattern_compiles(pattern: str, rule_id: str) -> bool:
    """Verify the regex compiles in Python (should always pass since it's from source)."""
    try:
        re.compile(pattern)
        return True
    except re.error as e:
        logger.warning("%s pattern doesn't compile in Python: %s", rule_id, e)
        return False


def generate_rule_block(rule: dict, comment: str = "") -> str:
    """Generate a single make_rule(...) call for one rule."""
    rid = rule["id"]
    sev = rule["severity"]
    langs = rule.get("lang", [])
    pattern = rule["pattern"]
    desc = rule["description"]
    fix = rule["fix_hint"]
    test = rule["test_hint"]

    validate_pattern_compiles(pattern, rid)

    lines = []
    if comment:
        lines.append(f"        // {rid}: {comment}")

    pat_literal = python_pattern_to_rust_literal(pattern)

    lines.append("        make_rule(")
    lines.append(f'            "{rid}", "{sev}", {rust_langs(langs)},')
    lines.append(f"            {pat_literal},")
    lines.append(f'            "{rust_string(desc)}",')
    lines.append(f'            "{rust_string(fix)}",')
    lines.append(f'            "{rust_string(test)}",')
    lines.append("        ),")
    return "\n".join(lines)


# ── Short description for each rule (for Rust comments) ───────────────────

RULE_COMMENTS = {
    "SEC-001": "XSS template literal — negative lookahead for sanitizers",
    "SEC-002": "XSS string concatenation",
    "SEC-003": "Command injection subprocess shell=True",
    "SEC-004": "SQL injection via f-string or %s",
    "SEC-005": "SSRF URL concatenation",
    "SEC-006": "CORS wildcard",
    "SEC-007": "eval/exec",
    "SEC-008": "Hardcoded secrets",
    "SEC-009": "Unsafe deserialization — negative lookahead for SafeLoader",
    "SEC-010": "Path traversal",
    "QUAL-001": "Bare except",
    "QUAL-002": "Silent exception swallowing",
    "QUAL-003": "Unchecked int() on user input",
    "QUAL-004": "Unchecked float() on user input",
    "QUAL-005": ".items() on potentially None",
    "QUAL-006": "Non-daemon thread",
    "QUAL-007": "TODO/FIXME",
    "QUAL-008": "Long sleep",
    "QUAL-009": "Explicit keep-alive header",
    "QUAL-010": "localStorage without try/catch — negative lookahead",
    "PY-001": "Return type mismatch",
    "PY-002": ".items() on None method return",
    "PY-003": "Wildcard import",
    "PY-004": "Debug print",
    "PY-005": "JSON parse without try — negative lookahead",
    "PY-006": "Global variable",
    "PY-007": "Direct environ[] access",
    "PY-008": "open() without encoding — negative lookahead",
}


def generate_fn(name: str, rules: list[dict], header: str) -> str:
    """Generate a complete Rust function that returns Vec<Rule>."""
    blocks = []
    for rule in rules:
        comment = RULE_COMMENTS.get(rule["id"], rule["description"][:60])
        blocks.append(generate_rule_block(rule, comment))

    rules_body = "\n".join(blocks)

    return f"""// ── {header} ──

fn {name}() -> Vec<Rule> {{
    [
{rules_body}
    ]
    .into_iter()
    .flatten()
    .collect()
}}"""


def generate_tests(all_rules: list[dict]) -> str:
    """Generate Rust unit tests that verify rule counts and IDs."""
    sec_count = sum(1 for r in all_rules if r["id"].startswith("SEC"))
    qual_count = sum(1 for r in all_rules if r["id"].startswith("QUAL"))
    py_count = sum(1 for r in all_rules if r["id"].startswith("PY"))
    total = len(all_rules)

    return f"""#[cfg(test)]
mod tests {{
    use super::*;

    #[test]
    fn test_all_{total}_rules_compile() {{
        let rules = get_all_rules();
        assert_eq!(rules.len(), {total}, "Expected {total} rules, got {{}}", rules.len());
    }}

    #[test]
    fn test_{sec_count}_security_rules() {{
        let rules = security_rules();
        assert_eq!(rules.len(), {sec_count});
        let ids: Vec<_> = rules.iter().map(|r| r.id.as_str()).collect();
        for i in 1..={sec_count} {{
            let id = format!("SEC-{{:03}}", i);
            assert!(ids.contains(&id.as_str()), "Missing {{id}}");
        }}
    }}

    #[test]
    fn test_{qual_count}_quality_rules() {{
        let rules = quality_rules();
        assert_eq!(rules.len(), {qual_count});
        let ids: Vec<_> = rules.iter().map(|r| r.id.as_str()).collect();
        for i in 1..={qual_count} {{
            let id = format!("QUAL-{{:03}}", i);
            assert!(ids.contains(&id.as_str()), "Missing {{id}}");
        }}
    }}

    #[test]
    fn test_{py_count}_python_rules() {{
        let rules = python_rules();
        assert_eq!(rules.len(), {py_count});
        let ids: Vec<_> = rules.iter().map(|r| r.id.as_str()).collect();
        for i in 1..={py_count} {{
            let id = format!("PY-{{:03}}", i);
            assert!(ids.contains(&id.as_str()), "Missing {{id}}");
        }}
    }}
}}"""


def generate_mod_rs() -> str:
    """Generate the complete mod.rs file."""
    all_rules = SECURITY_RULES + QUALITY_RULES + PYTHON_RULES
    total = len(all_rules)

    # Detect which rules use lookaheads (for the header comment)
    lookahead_rules = []
    for r in all_rules:
        if "(?!" in r["pattern"] or "(?=" in r["pattern"]:
            lookahead_rules.append(r["id"])
    lookahead_note = ", ".join(lookahead_rules) if lookahead_rules else "none"

    header = f"""//! Auto-generated from Python rules — DO NOT EDIT MANUALLY.
//! Re-generate with: python generate_rust_rules.py
//!
//! {total} rules mirroring xray/rules/*.py (single source of truth).
//! Uses fancy-regex for lookaheads ({lookahead_note}).

use fancy_regex::Regex;
use crate::Rule;

/// Build all {total} rules. Called once at startup.
pub fn get_all_rules() -> Vec<Rule> {{
    let mut rules = Vec::new();
    rules.extend(security_rules());
    rules.extend(quality_rules());
    rules.extend(python_rules());
    rules
}}

fn make_rule(
    id: &str, severity: &str, langs: &[&str],
    pattern: &str, desc: &str, fix: &str, test: &str,
) -> Option<Rule> {{
    let re = Regex::new(pattern).ok()?;
    Some(Rule {{
        id: id.to_string(),
        severity: severity.to_string(),
        langs: langs.iter().map(|s| s.to_string()).collect(),
        pattern: re,
        description: desc.to_string(),
        fix_hint: fix.to_string(),
        test_hint: test.to_string(),
    }})
}}"""

    sec_fn = generate_fn(
        "security_rules", SECURITY_RULES, f"SECURITY RULES (SEC-001 through SEC-{len(SECURITY_RULES):03d})"
    )
    qual_fn = generate_fn(
        "quality_rules", QUALITY_RULES, f"QUALITY RULES (QUAL-001 through QUAL-{len(QUALITY_RULES):03d})"
    )
    py_fn = generate_fn("python_rules", PYTHON_RULES, f"PYTHON RULES (PY-001 through PY-{len(PYTHON_RULES):03d})")
    tests = generate_tests(all_rules)

    return f"{header}\n\n{sec_fn}\n\n{qual_fn}\n\n{py_fn}\n\n{tests}\n"


def check_parity() -> bool:
    """Verify generated output matches what's on disk."""
    target = os.path.join(os.path.dirname(__file__), "scanner", "src", "rules", "mod.rs")
    if not os.path.exists(target):
        logger.error("mod.rs not found — run without --check first")
        return False

    generated = generate_mod_rs()
    with open(target, encoding="utf-8") as f:
        current = f.read()

    if generated == current:
        logger.info("PARITY OK — %s matches generated output", target)
        return True
    else:
        logger.error("DRIFT DETECTED — %s differs from generated output", target)
        # Show first difference
        gen_lines = generated.splitlines()
        cur_lines = current.splitlines()
        for i, (g, c) in enumerate(zip(gen_lines, cur_lines, strict=False), 1):
            if g != c:
                logger.error("  First diff at line %d:", i)
                logger.error("    Generated: %s", g[:120])
                logger.error("    Current:   %s", c[:120])
                break
        else:
            if len(gen_lines) != len(cur_lines):
                logger.error("  Line count differs: generated=%d current=%d", len(gen_lines), len(cur_lines))
        return False


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Generate Rust rules from Python source of truth")
    parser.add_argument("--check", action="store_true", help="Verify parity without writing")
    parser.add_argument("--dry-run", action="store_true", help="Print to stdout instead of file")
    args = parser.parse_args()

    if args.check:
        ok = check_parity()
        sys.exit(0 if ok else 1)

    output = generate_mod_rs()

    if args.dry_run:
        print(output)
    else:
        target = os.path.join(os.path.dirname(__file__), "scanner", "src", "rules", "mod.rs")
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(output)
        all_rules = SECURITY_RULES + QUALITY_RULES + PYTHON_RULES
        logger.info("Generated %s", target)
        logger.info(
            "  %d rules (%d security, %d quality, %d python)",
            len(all_rules),
            len(SECURITY_RULES),
            len(QUALITY_RULES),
            len(PYTHON_RULES),
        )

        # Verify the patterns round-trip correctly
        import re as re_mod

        errors = 0
        for rule in all_rules:
            try:
                re_mod.compile(rule["pattern"])
            except re_mod.error as e:
                logger.error("  %s regex doesn't compile: %s", rule["id"], e)
                errors += 1

        # Sanity: ensure generated output has the right number of make_rule calls
        # The pattern call + the fn definition = len(all_rules) + 1
        make_rule_count = output.count("        make_rule(")
        if make_rule_count != len(all_rules):
            logger.warning("  expected %d make_rule calls, got %d", len(all_rules), make_rule_count)
            errors += 1

        if errors == 0:
            logger.info("  All patterns validated OK")


if __name__ == "__main__":
    main()
