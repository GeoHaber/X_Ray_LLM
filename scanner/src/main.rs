//! X-Ray Scanner CLI — Fast code scanning from the command line.
//!
//! Usage:
//!   xray-scanner ./path/to/project
//!   xray-scanner ./src --severity HIGH
//!   xray-scanner . --json
//!   xray-scanner . --exclude "vendor/" "test/"

use clap::Parser;
use std::path::PathBuf;
use xray_scanner::{scan_directory_with_excludes, rules::get_all_rules};

#[derive(Parser)]
#[command(name = "xray-scanner")]
#[command(about = "High-performance code scanner for X-Ray LLM agent")]
struct Cli {
    /// Project directory to scan
    #[arg(default_value = ".")]
    path: PathBuf,

    /// Minimum severity: HIGH, MEDIUM, or LOW
    #[arg(long, default_value = "MEDIUM")]
    severity: String,

    /// Output as JSON
    #[arg(long)]
    json: bool,

    /// Regex patterns to exclude from scan
    #[arg(long, num_args = 0..)]
    exclude: Vec<String>,
}

fn main() {
    let cli = Cli::parse();
    let rules = get_all_rules();

    let result = scan_directory_with_excludes(&cli.path, &rules, &cli.exclude);

    // Filter by severity
    let severity_levels: Vec<&str> = match cli.severity.as_str() {
        "HIGH" => vec!["HIGH"],
        "MEDIUM" => vec!["HIGH", "MEDIUM"],
        _ => vec!["HIGH", "MEDIUM", "LOW"],
    };

    let filtered: Vec<_> = result
        .findings
        .iter()
        .filter(|f| severity_levels.contains(&f.severity.as_str()))
        .collect();

    if cli.json {
        let output = serde_json::json!({
            "files_scanned": result.files_scanned,
            "rules_checked": result.rules_checked,
            "findings": filtered,
            "summary": {
                "total": filtered.len(),
                "high": filtered.iter().filter(|f| f.severity == "HIGH").count(),
                "medium": filtered.iter().filter(|f| f.severity == "MEDIUM").count(),
                "low": filtered.iter().filter(|f| f.severity == "LOW").count(),
            }
        });
        println!("{}", serde_json::to_string_pretty(&output).unwrap());
    } else {
        println!("{}", result.summary());
        println!(
            "After severity filter (>={}): {} issues\n",
            cli.severity,
            filtered.len()
        );

        for f in &filtered {
            println!(
                "  [{}] {} -- {}:{} -- {}",
                f.severity, f.rule_id, f.file, f.line, f.description
            );
            println!("         Fix: {}", f.fix_hint);
        }

        if !result.errors.is_empty() {
            println!("\nErrors:");
            for e in &result.errors {
                println!("  {e}");
            }
        }
    }
}
