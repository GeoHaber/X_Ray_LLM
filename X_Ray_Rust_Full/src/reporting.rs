// src/reporting.rs — Unified report formatting (unified, zero duplication)
//
// Single summary() function replaces the 3 duplicated versions
// (lint.summary, security.summary, smells.summary) identified by X-Ray.

use crate::types::{DuplicateGroup, ScanResults, Severity, SmellIssue};
use colored::Colorize;

// ── Console Output ─────────────────────────────────────────────────

pub fn print_banner() {
    println!("{}", r#"
================================================================
  X-RAY v5.0.0 — Unified Code Quality Scanner (Rust)
  AST Smells + Ruff Lint + Bandit Security
================================================================
"#.bright_cyan());
}

/// Print smell report
pub fn print_smells(issues: &[SmellIssue]) {
    if issues.is_empty() {
        println!("\n  {} No code smells found!\n", "✓".green());
        return;
    }
    println!("\n{}", "-\nCODE SMELL REPORT (X-Ray)\n-".bright_white());
    for issue in issues {
        let icon = severity_icon(issue.severity);
        let label = format!("[{}]", issue.category.to_uppercase());
        let name_part = if issue.name.is_empty() {
            String::new()
        } else {
            format!(" in {}", issue.name)
        };
        println!("{} {}{}", icon, label.bold(), name_part);
        println!("    Location: {}:{}", issue.file_path, issue.line);
        println!("    Issue:    {}", issue.message);
        println!("    Fix:      {}\n", issue.suggestion.dimmed());
    }
    let (c, w, i) = count_severities(issues);
    println!("Summary: {} issues ({}critical, {}warning, {}info)",
        issues.len(), c, w, i);
}

/// Print duplicate groups
pub fn print_duplicates(groups: &[DuplicateGroup]) {
    if groups.is_empty() {
        println!("\n  {} No duplicates found!\n", "✓".green());
        return;
    }
    println!("\n{}", "-\nSIMILAR FUNCTIONS (X-Ray)\n-".bright_white());
    for g in groups {
        println!("Group {} ({}, avg sim: {:.2})",
            g.group_id,
            g.similarity_type,
            g.avg_similarity);
        for f in &g.functions {
            let file = f.get("file").and_then(|v| v.as_str()).unwrap_or("?");
            let line = f.get("line").and_then(|v| v.as_u64()).unwrap_or(0);
            let name = f.get("name").and_then(|v| v.as_str()).unwrap_or("?");
            println!("  - {}:{} ({})", file, line, name);
        }
        println!();
    }
}

/// Print lint issues
pub fn print_lint(issues: &[SmellIssue]) {
    if issues.is_empty() {
        println!("\n  {} No lint issues found!\n", "✓".green());
        return;
    }
    println!("\n{}", "-\nRUFF LINT REPORT\n-".bright_white());
    for issue in issues {
        let icon = severity_icon(issue.severity);
        println!("{} {} {}:{}  {}",
            icon, issue.rule_code.bold(), issue.file_path, issue.line, issue.message);
    }
    let (c, w, i) = count_severities(issues);
    println!("\nSummary: {} issues ({}critical, {}warning, {}info)",
        issues.len(), c, w, i);
}

/// Print security issues
pub fn print_security(issues: &[SmellIssue]) {
    if issues.is_empty() {
        println!("\n  {} No security issues found!\n", "✓".green());
        return;
    }
    println!("\n{}", "-\nBANDIT SECURITY REPORT\n-".bright_white());
    for issue in issues {
        let icon = severity_icon(issue.severity);
        println!("{} {} {}:{}  {}",
            icon, issue.rule_code.bold(), issue.file_path, issue.line, issue.message);
    }
    let (c, w, i) = count_severities(issues);
    println!("\nSummary: {} issues ({}critical, {}warning, {}info)",
        issues.len(), c, w, i);
}

/// Print unified grade
pub fn print_grade(results: &ScanResults) {
    let grade = results.grade();
    let total = results.total_issues();

    let grade_colored = match grade {
        "A" => grade.green().bold(),
        "B" => grade.bright_green().bold(),
        "C" => grade.yellow().bold(),
        "D" => grade.bright_red().bold(),
        _ => grade.red().bold(),
    };

    println!("\n{}", "================================================================".bright_cyan());
    println!("  {}", "UNIFIED CODE QUALITY GRADE".bright_white().bold());
    println!("{}", "================================================================".bright_cyan());

    let mut tools: Vec<&str> = Vec::new();
    if !results.smells.is_empty() { tools.push("X-Ray Smells"); }
    if !results.duplicates.is_empty() { tools.push("X-Ray Duplicates"); }
    if !results.lint_issues.is_empty() { tools.push("Ruff Lint"); }
    if !results.security_issues.is_empty() { tools.push("Bandit Security"); }
    println!("\n  Tools used: {}", tools.join(", "));

    // Score calculation
    let funcs = results.functions.len().max(1) as f64;
    let ratio = total as f64 / funcs;
    let score = ((1.0 - ratio.min(1.0)) * 100.0).max(0.0);
    println!("\n  Score: {:.1}/100  Grade: {}", score, grade_colored);
    println!("\n  {} total issues across {} functions\n",
        total.to_string().bold(), results.functions.len());
    println!("{}\n", "================================================================".bright_cyan());
}

/// Save JSON report
pub fn save_json_report(results: &ScanResults, path: &str) -> anyhow::Result<()> {
    let json = serde_json::to_string_pretty(results)?;
    std::fs::write(path, json)?;
    println!("  Report saved to {}", path.bright_green());
    Ok(())
}

// ── Helpers ────────────────────────────────────────────────────────

fn severity_icon(sev: Severity) -> &'static str {
    match sev {
        Severity::Critical => "\u{1f534}",
        Severity::Warning => "\u{1f7e1}",
        Severity::Info => "\u{1f535}",
    }
}

pub fn count_severities(issues: &[SmellIssue]) -> (usize, usize, usize) {
    let c = issues.iter().filter(|i| i.severity == Severity::Critical).count();
    let w = issues.iter().filter(|i| i.severity == Severity::Warning).count();
    let i = issues.iter().filter(|i| i.severity == Severity::Info).count();
    (c, w, i)
}
