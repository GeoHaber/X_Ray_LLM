//! X-Ray Scanner — Fast code scanning CLI + Web UI server.
//!
//! Usage:
//!   xray-scanner ./path/to/project          # CLI scan
//!   xray-scanner ./src --severity HIGH      # filter high only
//!   xray-scanner . --json                   # JSON output
//!   xray-scanner . --sarif out.sarif        # SARIF output
//!   xray-scanner --serve                    # Launch web UI on port 8077
//!   xray-scanner --serve --port 9000        # Custom port

use clap::Parser;
use std::path::PathBuf;
use xray_scanner::{scan_directory_with_excludes, rules::get_all_rules, sarif};

#[derive(Parser)]
#[command(name = "xray-scanner")]
#[command(about = "X-Ray LLM — High-performance code scanner & web UI (Rust edition)")]
struct Cli {
    /// Project directory to scan (CLI mode)
    #[arg(default_value = ".")]
    path: PathBuf,

    /// Minimum severity: HIGH, MEDIUM, or LOW
    #[arg(long, default_value = "MEDIUM")]
    severity: String,

    /// Output as JSON
    #[arg(long)]
    json: bool,

    /// Output SARIF file
    #[arg(long)]
    sarif: Option<String>,

    /// Launch web UI server instead of CLI scan
    #[arg(long)]
    serve: bool,

    /// Port for web UI server (default: 8077)
    #[arg(long, default_value = "8077")]
    port: u16,

    /// Regex patterns to exclude from scan
    #[arg(long, num_args = 0..)]
    exclude: Vec<String>,

    /// Enable incremental scanning (cache results)
    #[arg(long)]
    incremental: bool,
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt::init();

    let cli = Cli::parse();

    // Detect if launched by double-click (no real args besides the exe itself).
    // When the user just double-clicks the .exe, launch the web UI automatically.
    let launched_interactive = std::env::args().count() == 1;

    // ── Server mode ──────────────────────────────────────────────
    if cli.serve || launched_interactive {
        println!("╔══════════════════════════════════════════════════╗");
        println!("║   X-Ray LLM — Rust Scanner + Web UI             ║");
        println!("║   http://127.0.0.1:{:<30}║", cli.port);
        println!("╚══════════════════════════════════════════════════╝");
        println!();
        // Auto-open browser when launched interactively
        let url = format!("http://127.0.0.1:{}", cli.port);
        #[cfg(target_os = "windows")]
        { let _ = std::process::Command::new("cmd").args(["/C", "start", &url]).spawn(); }
        #[cfg(target_os = "macos")]
        { let _ = std::process::Command::new("open").arg(&url).spawn(); }
        #[cfg(target_os = "linux")]
        { let _ = std::process::Command::new("xdg-open").arg(&url).spawn(); }
        println!("Browser opened. Press Ctrl+C to stop the server.");
        if let Err(e) = xray_scanner::server::run_server(cli.port).await {
            eprintln!("Server error: {}", e);
            std::process::exit(1);
        }
        return;
    }

    // ── CLI scan mode ────────────────────────────────────────────
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

    // SARIF output
    if let Some(ref sarif_path) = cli.sarif {
        let findings_json: Vec<serde_json::Value> = result.findings.iter().map(|f| serde_json::json!({
            "rule_id": f.rule_id,
            "severity": f.severity,
            "file": f.file,
            "line": f.line,
            "description": f.description,
            "fix_hint": f.fix_hint,
        })).collect();
        match sarif::write_sarif(&findings_json, sarif_path) {
            Ok(_) => println!("SARIF written to {}", sarif_path),
            Err(e) => eprintln!("Failed to write SARIF: {}", e),
        }
        return;
    }

    if cli.json {
        let output = serde_json::json!({
            "files_scanned": result.files_scanned,
            "rules_checked": result.rules_checked,
            "findings": filtered,
            "grade": result.grade(),
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
        println!("Grade: {}\n", result.grade());
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

    // Pause so the console window stays open when double-clicked
    println!("\nPress Enter to exit...");
    let _ = std::io::stdin().read_line(&mut String::new());
}
