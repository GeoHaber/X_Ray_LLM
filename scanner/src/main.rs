//! X-Ray Scanner CLI — Fast code scanning from the command line.
//!
//! Usage:
//!   xray-scanner ./path/to/project
//!   xray-scanner ./src --severity HIGH
//!   xray-scanner . --json

use clap::Parser;
use std::path::PathBuf;
use xray_scanner::{scan_directory, rules::get_all_rules};

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
}

fn main() {
    let cli = Cli::parse();
    let rules = get_all_rules();

    let result = scan_directory(&cli.path, &rules);

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
        let json = serde_json::to_string_pretty(&filtered).unwrap();
        println!("{json}");
    } else {
        println!(
            "Scanned {} files against {} rules",
            result.files_scanned, result.rules_checked
        );
        println!(
            "Found {} issues ({} after severity filter)\n",
            result.findings.len(),
            filtered.len()
        );

        for f in &filtered {
            println!(
                "[{}] {} — {}:{} — {}",
                f.severity, f.rule_id, f.file, f.line, f.description
            );
        }
    }
}
