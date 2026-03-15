//! Security and quality rules compiled into Rust regexes.
//! Mirror of the Python rules for consistent results.

use regex::Regex;
use crate::Rule;

/// Build all rules. Called once at startup.
pub fn get_all_rules() -> Vec<Rule> {
    let mut rules = Vec::new();
    rules.extend(security_rules());
    rules.extend(quality_rules());
    rules.extend(python_rules());
    rules
}

fn make_rule(
    id: &str, severity: &str, langs: &[&str],
    pattern: &str, desc: &str, fix: &str, test: &str,
) -> Option<Rule> {
    let re = Regex::new(pattern).ok()?;
    Some(Rule {
        id: id.to_string(),
        severity: severity.to_string(),
        langs: langs.iter().map(|s| s.to_string()).collect(),
        pattern: re,
        description: desc.to_string(),
        fix_hint: fix.to_string(),
        test_hint: test.to_string(),
    })
}

fn security_rules() -> Vec<Rule> {
    [
        make_rule(
            "SEC-001", "HIGH", &["javascript", "html"],
            r"\.innerHTML\s*=.*\$\{",
            "XSS: Template literal injected into innerHTML without sanitization",
            "Wrap dynamic values with an HTML escape function",
            "Verify _escHtml wraps all dynamic values in innerHTML",
        ),
        make_rule(
            "SEC-003", "HIGH", &["python"],
            r"subprocess\.\w+\([^)]*shell\s*=\s*True",
            "Command injection: subprocess with shell=True",
            "Use shell=False and pass args as a list",
            "Verify subprocess calls do not use shell=True",
        ),
        make_rule(
            "SEC-005", "MEDIUM", &["python"],
            r"urlopen\([^)]*\+|requests\.\w+\([^)]*\+",
            "SSRF: URL constructed from user input",
            "Validate URLs against an allowlist",
            "Test URL validation rejects private IPs",
        ),
        make_rule(
            "SEC-006", "MEDIUM", &["python"],
            r#"Access-Control-Allow-Origin.*\*"#,
            "CORS wildcard allows any origin",
            "Restrict to specific trusted origins",
            "Verify CORS never returns wildcard",
        ),
        make_rule(
            "SEC-007", "HIGH", &["python", "javascript"],
            r"\beval\s*\(",
            "Code injection: eval() with potentially untrusted input",
            "Replace eval with safe alternatives",
            "Verify no eval on user-controlled data",
        ),
        make_rule(
            "SEC-009", "HIGH", &["python"],
            r"pickle\.loads?\(",
            "Unsafe deserialization with pickle",
            "Use json instead of pickle for untrusted data",
            "Verify no unsafe deserialization",
        ),
    ]
    .into_iter()
    .flatten()
    .collect()
}

fn quality_rules() -> Vec<Rule> {
    [
        make_rule(
            "QUAL-001", "MEDIUM", &["python"],
            r"except\s*:",
            "Bare except swallows all errors",
            "Catch specific exceptions",
            "Verify no bare except clauses",
        ),
        make_rule(
            "QUAL-003", "MEDIUM", &["python"],
            r"int\(\s*(request|qs|params|query)",
            "Unchecked int() on user input",
            "Wrap in try/except ValueError",
            "Test non-numeric input returns default",
        ),
        make_rule(
            "QUAL-009", "HIGH", &["python"],
            r"Connection:\s*keep-alive",
            "Explicit keep-alive may cause hangs",
            "Remove the Connection header",
            "Test responses close without hanging",
        ),
    ]
    .into_iter()
    .flatten()
    .collect()
}

fn python_rules() -> Vec<Rule> {
    [
        make_rule(
            "PY-005", "HIGH", &["python"],
            r"json\.loads?\([^)]+\)",
            "JSON parsing without error handling",
            "Wrap in try/except JSONDecodeError",
            "Test malformed JSON returns error",
        ),
        make_rule(
            "PY-007", "MEDIUM", &["python"],
            r#"os\.environ\["#,
            "Direct environ[] crashes on missing key",
            "Use os.environ.get() with default",
            "Verify env access has defaults",
        ),
    ]
    .into_iter()
    .flatten()
    .collect()
}
