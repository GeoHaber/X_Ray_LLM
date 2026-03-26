//! Project health checks, remediation time estimation, release readiness.
//! Rust port of analyzers/health.py.

use std::collections::HashMap;
use std::path::Path;
use walkdir::WalkDir;

use crate::constants::SKIP_DIRS;

/// A single health check result.
#[derive(Debug, Clone, serde::Serialize)]
pub struct HealthCheck {
    pub name: String,
    pub status: String,
    pub file: String,
    pub description: String,
    pub severity: String,
}

/// Aggregated health result.
#[derive(Debug, Clone, serde::Serialize)]
pub struct HealthResult {
    pub score: usize,
    pub passed: usize,
    pub total: usize,
    pub checks: Vec<HealthCheck>,
}

/// Remediation time estimate.
#[derive(Debug, Clone, serde::Serialize)]
pub struct RemediationEstimate {
    pub total_minutes: usize,
    pub total_hours: f64,
    pub per_finding: Vec<String>,
}

/// Check for essential project files and configuration.
pub fn check_project_health(directory: &str) -> HealthResult {
    let mut checks = Vec::new();

    let check_items: Vec<(&str, Vec<&str>, &str, &str)> = vec![
        ("README", vec!["README.md", "README.rst", "README.txt", "README"], "Project documentation", "HIGH"),
        ("LICENSE", vec!["LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "COPYING"], "License file", "MEDIUM"),
        (".gitignore", vec![".gitignore"], "Git ignore rules", "MEDIUM"),
        ("Requirements", vec!["requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "poetry.lock", "uv.lock"], "Dependency specification", "HIGH"),
        ("CI Config", vec![".github/workflows", ".gitlab-ci.yml", "Jenkinsfile", ".circleci", ".travis.yml", "azure-pipelines.yml"], "CI/CD configuration", "LOW"),
        ("Tests", vec!["tests", "test", "tests.py", "test.py"], "Test directory or file", "HIGH"),
        ("Type Hints", vec!["py.typed", "pyproject.toml", "mypy.ini", ".mypy.ini", "pyrightconfig.json"], "Type checking configuration", "LOW"),
        ("Linter Config", vec![".ruff.toml", "ruff.toml", "pyproject.toml", ".flake8", ".pylintrc", "tox.ini"], "Linter configuration", "LOW"),
        ("Changelog", vec!["CHANGELOG.md", "CHANGELOG.rst", "CHANGES.md", "HISTORY.md"], "Change log", "LOW"),
        ("Editor Config", vec![".editorconfig"], "Editor configuration", "LOW"),
    ];

    for (name, patterns, description, severity) in &check_items {
        let mut found = false;
        let mut found_file = patterns[0].to_string();
        for pat in patterns {
            let target = Path::new(directory).join(pat);
            if target.exists() {
                found = true;
                found_file = pat.to_string();
                break;
            }
        }
        checks.push(HealthCheck {
            name: name.to_string(),
            status: if found { "pass" } else { "fail" }.to_string(),
            file: found_file,
            description: description.to_string(),
            severity: severity.to_string(),
        });
    }

    let passed = checks.iter().filter(|c| c.status == "pass").count();
    let total = checks.len();
    let score = if total > 0 { (passed * 100) / total } else { 0 };

    HealthResult { score, passed, total, checks }
}

/// Estimate remediation time per finding based on rule category.
pub fn estimate_remediation_time(findings: &[serde_json::Value]) -> RemediationEstimate {
    let time_map: HashMap<&str, (&str, usize)> = [
        ("SEC-", ("~15 min", 15)),
        ("QUAL-", ("~5 min", 5)),
        ("PY-", ("~10 min", 10)),
        ("PORT-", ("~10 min", 10)),
    ].iter().cloned().collect();

    let mut total_min = 0;
    let mut estimates = Vec::new();

    for f in findings {
        let rule_id = f.get("rule_id").and_then(|v| v.as_str()).unwrap_or("");
        let (label, minutes) = time_map
            .iter()
            .find(|(prefix, _)| rule_id.starts_with(*prefix))
            .map(|(_, v)| *v)
            .unwrap_or(("~10 min", 10));
        total_min += minutes;
        estimates.push(label.to_string());
    }

    RemediationEstimate {
        total_minutes: total_min,
        total_hours: (total_min as f64 / 60.0 * 10.0).round() / 10.0,
        per_finding: estimates,
    }
}

/// Assess release readiness based on multiple criteria.
pub fn check_release_readiness(directory: &str) -> serde_json::Value {
    let mut checks = Vec::new();
    let dir = Path::new(directory);

    // Version in pyproject.toml
    let has_version = dir.join("pyproject.toml")
        .is_file()
        && std::fs::read_to_string(dir.join("pyproject.toml"))
            .unwrap_or_default()
            .to_lowercase()
            .contains("version");
    checks.push(serde_json::json!({"name": "Version defined", "pass": has_version, "severity": "HIGH"}));

    // Changelog exists
    let changelog = ["CHANGELOG.md", "CHANGELOG.rst", "CHANGES.md", "HISTORY.md"]
        .iter()
        .any(|f| dir.join(f).exists());
    checks.push(serde_json::json!({"name": "Changelog exists", "pass": changelog, "severity": "MEDIUM"}));

    // No critical TODOs
    let critical_re = regex::Regex::new(r"(?i)\b(FIXME|XXX|BUG)\b").unwrap();
    let mut critical_todos = 0usize;
    for entry in walk_py_files(directory) {
        if let Ok(content) = std::fs::read_to_string(&entry) {
            for line in content.lines() {
                if critical_re.is_match(line) {
                    critical_todos += 1;
                }
            }
        }
    }
    checks.push(serde_json::json!({
        "name": format!("No critical TODOs ({critical_todos} found)"),
        "pass": critical_todos == 0,
        "severity": "HIGH"
    }));

    // Tests exist
    let tests = ["tests", "test"].iter().any(|d| dir.join(d).is_dir());
    checks.push(serde_json::json!({"name": "Tests exist", "pass": tests, "severity": "HIGH"}));

    // README exists
    let readme = ["README.md", "README.rst", "README"].iter().any(|f| dir.join(f).exists());
    checks.push(serde_json::json!({"name": "README exists", "pass": readme, "severity": "MEDIUM"}));

    let passed = checks.iter().filter(|c| c["pass"].as_bool().unwrap_or(false)).count();
    let total = checks.len();
    let score = if total > 0 { (passed * 100) / total } else { 0 };

    serde_json::json!({
        "ready": passed == total,
        "score": score,
        "passed": passed,
        "total": total,
        "checks": checks,
    })
}

/// Walk Python files in a directory (utility).
fn walk_py_files(directory: &str) -> Vec<std::path::PathBuf> {
    let mut result = Vec::new();
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
        if entry.file_type().is_file() {
            if let Some("py") = entry.path().extension().and_then(|e| e.to_str()) {
                result.push(entry.path().to_path_buf());
            }
        }
    }
    result
}
