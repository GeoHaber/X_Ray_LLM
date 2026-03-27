//! Security analysis — Bandit integration + AST-based secret detection.
//! Rust transpilation of analyzers/security.py.

use regex::Regex;
use std::collections::HashMap;
use std::process::Command;
use walkdir::WalkDir;

use crate::constants::SKIP_DIRS;

/// Forward-slash normaliser.
fn fwd(p: &str) -> String {
    p.replace('\\', "/")
}

/// Shannon entropy of a string.
fn entropy(s: &str) -> f64 {
    if s.is_empty() {
        return 0.0;
    }
    let mut freq: HashMap<char, usize> = HashMap::new();
    for c in s.chars() {
        *freq.entry(c).or_insert(0) += 1;
    }
    let length = s.len() as f64;
    -freq
        .values()
        .map(|&c| {
            let p = c as f64 / length;
            p * p.log2()
        })
        .sum::<f64>()
}

struct ApiKeyPattern {
    pattern: Regex,
    rule_id: &'static str,
    description: &'static str,
}

/// Run Bandit security scanner + AST-based secret detection.
/// Transpiled from security.py::run_bandit().
pub fn run_bandit(directory: &str) -> serde_json::Value {
    let mut bandit_issues: Vec<serde_json::Value> = Vec::new();
    let mut secrets: Vec<serde_json::Value> = Vec::new();

    // Run bandit if available
    match Command::new("bandit")
        .args(["-r", "-f", "json", "-q", directory])
        .output()
    {
        Ok(output) => {
            let stdout = String::from_utf8_lossy(&output.stdout);
            if !stdout.trim().is_empty() {
                if let Ok(data) = serde_json::from_str::<serde_json::Value>(&stdout) {
                    if let Some(results) = data.get("results").and_then(|r| r.as_array()) {
                        for issue in results {
                            bandit_issues.push(serde_json::json!({
                                "file": fwd(issue.get("filename").and_then(|f| f.as_str()).unwrap_or("")),
                                "line": issue.get("line_number").and_then(|l| l.as_u64()).unwrap_or(0),
                                "severity": issue.get("issue_severity").and_then(|s| s.as_str()).unwrap_or("MEDIUM").to_uppercase(),
                                "confidence": issue.get("issue_confidence").and_then(|c| c.as_str()).unwrap_or("MEDIUM").to_uppercase(),
                                "rule_id": issue.get("test_id").and_then(|t| t.as_str()).unwrap_or(""),
                                "rule_name": issue.get("test_name").and_then(|t| t.as_str()).unwrap_or(""),
                                "description": issue.get("issue_text").and_then(|t| t.as_str()).unwrap_or(""),
                                "cwe": issue.get("issue_cwe").and_then(|c| c.get("id")).and_then(|id| id.as_str()).unwrap_or(""),
                            }));
                        }
                    }
                }
            }
        }
        Err(_) => {
            // bandit not installed, skip
        }
    }

    // AST-based secret detection
    let api_key_patterns = vec![
        ApiKeyPattern {
            pattern: Regex::new(r"sk-[a-zA-Z0-9]{20,}").unwrap(),
            rule_id: "XS001",
            description: "OpenAI API key detected",
        },
        ApiKeyPattern {
            pattern: Regex::new(r"ghp_[a-zA-Z0-9]{36,}").unwrap(),
            rule_id: "XS001",
            description: "GitHub personal access token",
        },
        ApiKeyPattern {
            pattern: Regex::new(r"gho_[a-zA-Z0-9]{36,}").unwrap(),
            rule_id: "XS001",
            description: "GitHub OAuth token",
        },
        ApiKeyPattern {
            pattern: Regex::new(r"AKIA[0-9A-Z]{16}").unwrap(),
            rule_id: "XS001",
            description: "AWS Access Key ID",
        },
        ApiKeyPattern {
            pattern: Regex::new(r"xox[bpsar]-[a-zA-Z0-9\-]+").unwrap(),
            rule_id: "XS001",
            description: "Slack token",
        },
        ApiKeyPattern {
            pattern: Regex::new(r"AIza[0-9A-Za-z\-_]{35}").unwrap(),
            rule_id: "XS001",
            description: "Google API key",
        },
        ApiKeyPattern {
            pattern: Regex::new(r"EAAC[a-zA-Z0-9]+").unwrap(),
            rule_id: "XS001",
            description: "Facebook access token",
        },
    ];

    let suspicious_names =
        Regex::new(r"(?i)(api_key|apikey|secret|password|passwd|token|auth_token|access_key|private_key|credentials)")
            .unwrap();
    let assign_re = Regex::new(r#"=\s*["']([^"']{8,})["']"#).unwrap();

    for entry in WalkDir::new(directory)
        .into_iter()
        .filter_entry(|e| {
            if e.file_type().is_dir() {
                let name = e.file_name().to_str().unwrap_or("");
                !SKIP_DIRS.contains(&name) && !name.starts_with('.')
            } else {
                true
            }
        })
        .filter_map(|e| e.ok())
    {
        if !entry.file_type().is_file() {
            continue;
        }
        let path = entry.path();
        if path.extension().and_then(|e| e.to_str()) != Some("py") {
            continue;
        }

        let content = match std::fs::read_to_string(path) {
            Ok(c) => c,
            Err(_) => continue,
        };
        let rel = path
            .strip_prefix(directory)
            .unwrap_or(path)
            .to_string_lossy()
            .replace('\\', "/");

        for (lineno, line) in content.lines().enumerate() {
            let lineno = lineno + 1;

            // Check API key patterns
            let mut found_key = false;
            for akp in &api_key_patterns {
                if akp.pattern.is_match(line) {
                    let matched = line.trim();
                    let matched = if matched.len() > 100 {
                        &matched[..100]
                    } else {
                        matched
                    };
                    secrets.push(serde_json::json!({
                        "file": fwd(&rel),
                        "line": lineno,
                        "severity": "HIGH",
                        "rule_id": akp.rule_id,
                        "description": akp.description,
                        "matched": matched,
                    }));
                    found_key = true;
                    break;
                }
            }

            if found_key {
                continue;
            }

            // Check suspicious variable assignments
            if line.contains('=') && !line.trim_start().starts_with('#') {
                if let Some(name_match) = suspicious_names.find(line) {
                    if let Some(caps) = assign_re.captures(line) {
                        let value = caps.get(1).map(|m| m.as_str()).unwrap_or("");
                        if entropy(value) > 4.0 {
                            let matched = line.trim();
                            let matched = if matched.len() > 100 {
                                &matched[..100]
                            } else {
                                matched
                            };
                            secrets.push(serde_json::json!({
                                "file": fwd(&rel),
                                "line": lineno,
                                "severity": "HIGH",
                                "rule_id": "XS002",
                                "description": format!("Possible hardcoded secret in '{}'", name_match.as_str()),
                                "matched": matched,
                            }));
                        }
                    }
                }
            }
        }
    }

    let total_issues = bandit_issues.len() + secrets.len();

    serde_json::json!({
        "bandit_available": !bandit_issues.is_empty() || true,
        "bandit_issues": bandit_issues,
        "secrets": secrets,
        "total_issues": total_issues,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_entropy() {
        assert!(entropy("") == 0.0);
        assert!(entropy("aaaa") < 1.0);
        assert!(entropy("abcdefghijklmnop") > 3.0);
    }

    #[test]
    fn test_run_bandit_empty_dir() {
        let tmp = tempfile::tempdir().unwrap();
        let proj = tmp.path().join("project");
        std::fs::create_dir_all(&proj).unwrap();
        let result = run_bandit(proj.to_str().unwrap());
        assert_eq!(result["total_issues"].as_u64().unwrap(), 0);
    }

    #[test]
    fn test_secret_detection() {
        let tmp = tempfile::tempdir().unwrap();
        let proj = tmp.path().join("project");
        std::fs::create_dir_all(&proj).unwrap();
        std::fs::write(
            proj.join("secrets.py"),
            "api_key = \"sk-abcdefghijklmnopqrstuvwx\"\n",
        )
        .unwrap();
        let result = run_bandit(proj.to_str().unwrap());
        assert!(result["secrets"].as_array().unwrap().len() >= 1);
    }
}
