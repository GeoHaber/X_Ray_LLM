//! Auto-generated from Python rules — DO NOT EDIT MANUALLY.
//! Re-generate with: python generate_rust_rules.py
//!
//! 28 rules mirroring xray/rules/*.py (single source of truth).
//! Uses fancy-regex for lookaheads (SEC-001, SEC-009, QUAL-005, QUAL-010, PY-005, PY-008).

use fancy_regex::Regex;
use crate::Rule;

/// Build all 28 rules. Called once at startup.
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
    make_rule_cwe(id, severity, langs, pattern, desc, fix, test, "", "")
}

fn make_rule_cwe(
    id: &str, severity: &str, langs: &[&str],
    pattern: &str, desc: &str, fix: &str, test: &str,
    cwe: &str, owasp: &str,
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
        cwe: cwe.to_string(),
        owasp: owasp.to_string(),
    })
}

// ── SECURITY RULES (SEC-001 through SEC-010) ──

fn security_rules() -> Vec<Rule> {
    [
        make_rule_cwe("SEC-001", "HIGH", &["javascript", "html"],
            r"\.innerHTML\s*=\s*`[^`]*\$\{(?!.*_escHtml|.*escapeHtml|.*sanitize|.*DOMPurify|.*textContent)",
            "XSS: Template literal injected into innerHTML without sanitization",
            "Wrap all dynamic values with an HTML escape function or use textContent",
            "Verify _escHtml or equivalent sanitizer wraps all dynamic values in innerHTML assignments",
            "CWE-79", "A03:2021-Injection"),
        make_rule_cwe("SEC-002", "HIGH", &["javascript", "html"],
            r#"\.innerHTML\s*=\s*['\"][^'\"]*['\"]\s*\+\s*\w+"#,
            "XSS: String concatenation with variable injected into innerHTML",
            "Use textContent or sanitize the variable before injection",
            "Check that no unsanitized variables are concatenated into innerHTML",
            "CWE-79", "A03:2021-Injection"),
        make_rule_cwe("SEC-003", "HIGH", &["python"],
            r"(subprocess\.(run|call|Popen|check_output)\([^)]*\b(shell\s*=\s*True))",
            "Command injection: subprocess called with shell=True",
            "Use shell=False and pass args as a list",
            "Verify subprocess calls do not use shell=True with user-controlled input",
            "CWE-78", "A03:2021-Injection"),
        make_rule_cwe("SEC-004", "HIGH", &["python"],
            r#"(execute|executemany)\(\s*(f['\"].*\{.*\}.*['\"]|['\"].*%s)"#,
            "SQL injection: String formatting in SQL query",
            "Use parameterized queries with ? or %s placeholders",
            "Verify SQL queries use parameterized binding, not string formatting",
            "CWE-89", "A03:2021-Injection"),
        make_rule_cwe("SEC-005", "MEDIUM", &["python"],
            r#"urlopen\(.*\+|urlopen\(f['\"]|requests\.(get|post|put|delete)\(.*\+"#,
            "SSRF: URL constructed from user input without validation",
            "Validate URLs against an allowlist of trusted hosts before making requests",
            "Test that URL validation rejects internal/private IPs and non-allowlisted hosts",
            "CWE-918", "A10:2021-SSRF"),
        make_rule_cwe("SEC-006", "MEDIUM", &["python"],
            r#"Access-Control-Allow-Origin['\"],?\s*['\"]?\*"#,
            "CORS misconfiguration: wildcard origin allows any site",
            "Restrict CORS to specific trusted origins (e.g., localhost)",
            "Verify CORS headers never return wildcard (*) for credentialed requests",
            "CWE-942", "A05:2021-Security Misconfiguration"),
        make_rule_cwe("SEC-007", "HIGH", &["python", "javascript"],
            r"(eval|exec)\s*\(",
            "Code injection: eval/exec with potentially untrusted input",
            "Replace eval/exec with safe alternatives (ast.literal_eval, JSON.parse)",
            "Verify no eval/exec is used on user-controlled data",
            "CWE-94", "A03:2021-Injection"),
        make_rule_cwe("SEC-008", "MEDIUM", &["python"],
            r#"(password|secret|token|api_key)\s*=\s*['\"][^'\"]+['\"]"#,
            "Hardcoded secret: credential embedded in source code",
            "Move secrets to environment variables or a secrets manager",
            "Verify no hardcoded passwords/tokens/keys exist in source code",
            "CWE-798", "A07:2021-Identification and Authentication Failures"),
        make_rule_cwe("SEC-009", "HIGH", &["python"],
            r"pickle\.loads?\(|yaml\.load\([^)]*(?!Loader\s*=\s*yaml\.SafeLoader)",
            "Deserialization attack: unsafe pickle/yaml loading",
            "Use json or yaml.safe_load instead of pickle.loads/yaml.load",
            "Verify no unsafe deserialization is used on untrusted data",
            "CWE-502", "A08:2021-Software and Data Integrity Failures"),
        make_rule_cwe("SEC-010", "MEDIUM", &["python"],
            r"os\.path\.join\(.*\.\.\s*/",
            "Path traversal: user input may escape intended directory",
            "Validate and normalize paths, reject '..' components",
            "Verify path inputs are sanitized against directory traversal",
            "CWE-22", "A01:2021-Broken Access Control"),
    ]
    .into_iter()
    .flatten()
    .collect()
}

// ── QUALITY RULES (QUAL-001 through QUAL-010) ──

fn quality_rules() -> Vec<Rule> {
    [
        // QUAL-001: Bare except
        make_rule(
            "QUAL-001", "MEDIUM", &["python"],
            r"except\s*:",
            "Bare except clause swallows all errors including KeyboardInterrupt",
            "Catch specific exceptions: except (ValueError, TypeError):",
            "Verify no bare except clauses exist — all should name specific exceptions",
        ),
        // QUAL-002: Silent exception swallowing
        make_rule(
            "QUAL-002", "LOW", &["python"],
            r"except\s+\w+(\s*,\s*\w+)*\s*:\s*\n\s*pass",
            "Silent exception swallowing — error caught but ignored",
            "At minimum log the error; better: handle or re-raise",
            "Verify caught exceptions are logged or handled, not silently passed",
        ),
        // QUAL-003: Unchecked int() on user input
        make_rule(
            "QUAL-003", "MEDIUM", &["python"],
            r"int\(\s*(request|qs|params|args|query|self\.path|environ)\b[^)]*\)",
            "Unchecked int() on user input — will crash on non-numeric values",
            "Wrap in try/except ValueError with a sensible default",
            "Test that non-numeric input to this parameter returns a default, not a 500",
        ),
        // QUAL-004: Unchecked float() on user input
        make_rule(
            "QUAL-004", "MEDIUM", &["python"],
            r"float\(\s*(request|qs|params|args|query|self\.path|environ)\b[^)]*\)",
            "Unchecked float() on user input — will crash on non-numeric values",
            "Wrap in try/except ValueError with a sensible default",
            "Test that non-numeric input returns a default, not a crash",
        ),
        // QUAL-005: .items() on potentially None
        make_rule(
            "QUAL-005", "LOW", &["python"],
            r"\.items\(\)\s*$(?!\s*(if|for|return))",
            "Calling .items() on a potentially None return — NoneType has no attribute items",
            "Ensure the object is not None before calling .items(), or use (x or {}).items()",
            "Verify .items() is not called on functions that may return None",
        ),
        // QUAL-006: Non-daemon thread
        make_rule(
            "QUAL-006", "MEDIUM", &["python"],
            r"threading\.Thread\(.*daemon\s*=\s*False",
            "Non-daemon thread may prevent clean shutdown",
            "Set daemon=True for background worker threads",
            "Verify background threads are daemon threads so process can exit cleanly",
        ),
        // QUAL-007: TODO/FIXME
        make_rule(
            "QUAL-007", "LOW", &["python", "javascript"],
            r"(TODO|FIXME|HACK|XXX|TEMP)\b",
            "TODO/FIXME marker left in code",
            "Address the TODO or create a tracking issue",
            "Audit that TODO/FIXME comments have been addressed before release",
        ),
        // QUAL-008: Long sleep
        make_rule(
            "QUAL-008", "MEDIUM", &["python"],
            r"time\.sleep\(\s*\d{2,}\s*\)",
            "Long sleep (10+ seconds) in code — may indicate polling instead of events",
            "Use threading.Event, asyncio, or callback patterns instead of long sleeps",
            "Verify sleeps are short or replaced with event-driven patterns",
        ),
        // QUAL-009: Explicit keep-alive header
        make_rule(
            "QUAL-009", "HIGH", &["python"],
            r#"send_header\(['\"]Connection['\"]\s*,\s*['\"]keep-alive['\"]"#,
            "Explicit keep-alive header — may cause connection hang in some HTTP servers",
            "Remove Connection: keep-alive header; let the server/framework handle it",
            "Test that HTTP responses close correctly without hanging",
        ),
        // QUAL-010: localStorage without try/catch — negative lookahead
        make_rule(
            "QUAL-010", "MEDIUM", &["javascript", "html"],
            r"localStorage\.(setItem|getItem)\([^)]+\)(?!.*try|.*catch)",
            "localStorage access without try/catch — fails in private browsing",
            "Wrap localStorage access in try/catch for Safari private mode compatibility",
            "Test that localStorage failure (quota exceeded, private mode) is handled gracefully",
        ),
    ]
    .into_iter()
    .flatten()
    .collect()
}

// ── PYTHON RULES (PY-001 through PY-008) ──

fn python_rules() -> Vec<Rule> {
    [
        // PY-001: Return type mismatch
        make_rule(
            "PY-001", "MEDIUM", &["python"],
            r"def\s+\w+\(.*\)\s*->\s*None:.*\n.*return\s+\{",
            "Function annotated as -> None but returns a dict",
            "Fix the return type annotation to match actual return value",
            "Verify function return types match their annotations",
        ),
        // PY-002: .items() on None method return
        make_rule(
            "PY-002", "HIGH", &["python"],
            r"def\s+\w+\([^)]*\bself\b[^)]*\).*\n(?:.*\n)*?.*\bself\.\w+\(.*\)\.items\(\)",
            "Calling .items() on method that returns None (common in HTTP handlers)",
            "Check if the method returns a dict or None before calling .items()",
            "Test that methods returning None are not iterated with .items()",
        ),
        // PY-003: Wildcard import
        make_rule(
            "PY-003", "MEDIUM", &["python"],
            r"import\s+\*|from\s+\w+\s+import\s+\*",
            "Wildcard import pollutes namespace and hides dependencies",
            "Import specific names: from module import func1, func2",
            "Verify no wildcard imports exist in production code",
        ),
        // PY-004: Debug print
        make_rule(
            "PY-004", "LOW", &["python"],
            r"print\s*\(",
            "Debug print statement left in code — use logging instead",
            "Replace print() with logging.debug/info/warning as appropriate",
            "Verify production code uses logging module instead of print()",
        ),
        // PY-005: JSON parse without try — negative lookahead
        make_rule(
            "PY-005", "HIGH", &["python"],
            r"(json\.loads|json\.load)\([^)]+\)(?!\s*#\s*nosec)(?!.*try|.*except)",
            "JSON parsing without error handling — crashes on malformed input",
            "Wrap json.loads() in try/except json.JSONDecodeError",
            "Test that malformed JSON input returns an error response, not a crash",
        ),
        // PY-006: Global variable
        make_rule(
            "PY-006", "MEDIUM", &["python"],
            r"global\s+\w+",
            "Global variable mutation — hard to test and reason about",
            "Pass state through function parameters or use a class",
            "Verify global state is minimized and thread-safe if concurrent",
        ),
        // PY-007: Direct environ[] access
        make_rule(
            "PY-007", "MEDIUM", &["python"],
            r"os\.environ\[",
            "Direct os.environ[] access crashes on missing key — use .get() with default",
            "Use os.environ.get('KEY', 'default') instead of os.environ['KEY']",
            "Verify environment variable access has defaults for missing keys",
        ),
        // PY-008: open() without encoding — negative lookahead
        make_rule(
            "PY-008", "MEDIUM", &["python"],
            r#"\bopen\((?![^)]*(?:encoding|['\"]r?b['\"]))[^)]+\)"#,
            "File opened without explicit encoding — platform-dependent behavior",
            "Always specify encoding='utf-8' for text file operations",
            "Verify all text file opens specify explicit encoding",
        ),
    ]
    .into_iter()
    .flatten()
    .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_all_28_rules_compile() {
        let rules = get_all_rules();
        assert_eq!(rules.len(), 28, "Expected 28 rules, got {}", rules.len());
    }

    #[test]
    fn test_10_security_rules() {
        let rules = security_rules();
        assert_eq!(rules.len(), 10);
        let ids: Vec<_> = rules.iter().map(|r| r.id.as_str()).collect();
        for i in 1..=10 {
            let id = format!("SEC-{:03}", i);
            assert!(ids.contains(&id.as_str()), "Missing {id}");
        }
    }

    #[test]
    fn test_10_quality_rules() {
        let rules = quality_rules();
        assert_eq!(rules.len(), 10);
        let ids: Vec<_> = rules.iter().map(|r| r.id.as_str()).collect();
        for i in 1..=10 {
            let id = format!("QUAL-{:03}", i);
            assert!(ids.contains(&id.as_str()), "Missing {id}");
        }
    }

    #[test]
    fn test_8_python_rules() {
        let rules = python_rules();
        assert_eq!(rules.len(), 8);
        let ids: Vec<_> = rules.iter().map(|r| r.id.as_str()).collect();
        for i in 1..=8 {
            let id = format!("PY-{:03}", i);
            assert!(ids.contains(&id.as_str()), "Missing {id}");
        }
    }
}
