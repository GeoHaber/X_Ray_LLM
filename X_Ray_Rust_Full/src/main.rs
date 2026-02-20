// src/main.rs — X-Ray CLI entry point (optimized, zero duplication)
//
// This is the Rust equivalent of x_ray_claude.py, compiled to a native
// Windows/Mac/Linux executable. All duplicate patterns identified by
// X-Ray's self-scan have been eliminated.
#![allow(dead_code)]

mod ast_parse;
mod config;
mod duplicates;
mod external;
mod reporting;
mod similarity;
mod smells;
mod tokenizer;
mod types;

use clap::Parser;
use std::path::PathBuf;
use std::time::Instant;
use types::ScanResults;

#[derive(Parser, Debug)]
#[command(
    name = "X_Ray",
    version = config::VERSION,
    about = "X-Ray: Unified Python Code Quality Scanner (Rust)",
    long_about = "Scans Python codebases for code smells, duplicates, lint issues, and security vulnerabilities.\nBuilt from optimized, deduplicated building blocks."
)]
struct Args {
    /// Path to the directory to analyze
    #[arg(short, long, default_value = ".")]
    path: PathBuf,

    /// Run code smell detection
    #[arg(long)]
    smell: bool,

    /// Run duplicate/similar function detection
    #[arg(long)]
    duplicates: bool,

    /// Run Ruff lint analysis
    #[arg(long)]
    lint: bool,

    /// Run Bandit security analysis
    #[arg(long)]
    security: bool,

    /// Run all analyzers
    #[arg(long)]
    full_scan: bool,

    /// Save JSON report to file
    #[arg(long)]
    report: Option<String>,

    /// Directories to exclude
    #[arg(long, num_args = 0..)]
    exclude: Vec<String>,
}

fn main() {
    let mut args = Args::parse();

    // Auto-select: if no flags → smell + lint + security
    if !args.smell && !args.duplicates && !args.lint && !args.security && !args.full_scan {
        args.smell = true;
        args.lint = true;
        args.security = true;
    }
    if args.full_scan {
        args.smell = true;
        args.duplicates = true;
        args.lint = true;
        args.security = true;
    }

    let root = std::fs::canonicalize(&args.path).unwrap_or_else(|_| args.path.clone());

    reporting::print_banner();

    // ── Phase 1: Scan codebase ─────────────────────────────────────
    let t0 = Instant::now();
    let (functions, classes, errors) = ast_parse::scan_codebase(&root, &args.exclude, &[]);
    let scan_time = t0.elapsed();

    println!("  Scanning {} files...", ast_parse::collect_py_files(&root, &args.exclude, &[]).len());
    println!("  Scanned {} functions, {} classes in {:.2}s\n",
        functions.len(), classes.len(), scan_time.as_secs_f64());

    if !errors.is_empty() {
        eprintln!("  {} parse errors (use --report to see details)", errors.len());
    }

    let mut results = ScanResults::new();
    results.functions = functions.clone();
    results.classes = classes.clone();
    results.errors = errors;

    // ── Phase 2: Analysis ──────────────────────────────────────────
    if args.smell {
        println!("  >> Analyzing Code Smells (X-Ray)...");
        let thresholds = config::SmellThresholds::default();
        results.smells = smells::detect(&functions, &classes, &thresholds);
        reporting::print_smells(&results.smells);
    }

    if args.duplicates {
        println!("  >> Finding Duplicates...");
        results.duplicates = duplicates::find_duplicates(&functions);
        reporting::print_duplicates(&results.duplicates);
    }

    if args.lint {
        println!("  >> Running Ruff Lint...");
        if external::is_available(external::Tool::Ruff) {
            results.lint_issues = external::analyze(external::Tool::Ruff, &root, &args.exclude);
            reporting::print_lint(&results.lint_issues);
        } else {
            println!("  ⚠ ruff not found on PATH — skipping lint analysis");
        }
    }

    if args.security {
        println!("  >> Running Bandit Security...");
        if external::is_available(external::Tool::Bandit) {
            results.security_issues = external::analyze(external::Tool::Bandit, &root, &args.exclude);
            reporting::print_security(&results.security_issues);
        } else {
            println!("  ⚠ bandit not found on PATH — skipping security analysis");
        }
    }

    // ── Phase 3: Grade & Report ────────────────────────────────────
    reporting::print_grade(&results);

    if let Some(ref report_path) = args.report {
        if let Err(e) = reporting::save_json_report(&results, report_path) {
            eprintln!("  Error saving report: {}", e);
        }
    }
}
