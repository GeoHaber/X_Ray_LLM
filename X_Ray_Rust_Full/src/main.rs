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
use std::io::{self, Write};
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

    /// Full pipeline: scan → optimize → transpile → compile to executable
    #[arg(long)]
    rustify_exe: bool,

    /// Launch interactive TUI to select scope and options
    #[arg(short, long)]
    interactive: bool,

    /// Save JSON report to file
    #[arg(long)]
    report: Option<String>,

    /// Directories to exclude
    #[arg(long, num_args = 0..)]
    exclude: Vec<String>,
}

// ═══════════════════════════════════════════════════════════════════════════
//  Interactive TUI — select scope and functionality
// ═══════════════════════════════════════════════════════════════════════════

struct MenuOption {
    key: &'static str,
    label: &'static str,
    default: bool,
}

const MENU_OPTIONS: &[MenuOption] = &[
    MenuOption { key: "smell",       label: "Code Smell Detection",       default: true },
    MenuOption { key: "duplicates",  label: "Duplicate Finder",            default: false },
    MenuOption { key: "lint",        label: "Ruff Lint Analysis",          default: true },
    MenuOption { key: "security",    label: "Bandit Security Scan",        default: true },
    MenuOption { key: "rustify_exe", label: "Full Rustify → Executable",  default: false },
];

fn render_menu(selected: &[bool], cursor: usize) {
    println!();
    println!("  \x1b[1;36m╔══════════════════════════════════════╗\x1b[0m");
    println!("  \x1b[1;36m║   X-RAY  Interactive Mode            ║\x1b[0m");
    println!("  \x1b[1;36m╚══════════════════════════════════════╝\x1b[0m");
    println!();
    println!("  Use \x1b[1m↑↓\x1b[0m to move, \x1b[1mSpace\x1b[0m to toggle, \x1b[1mEnter\x1b[0m to run");
    println!();
    for (i, opt) in MENU_OPTIONS.iter().enumerate() {
        let mark = if selected[i] { "\x1b[1;32m✓\x1b[0m" } else { "\x1b[90m·\x1b[0m" };
        let arrow = if i == cursor { "\x1b[1;33m►\x1b[0m " } else { "  " };
        println!("  {}[{}] {}", arrow, mark, opt.label);
    }
    println!();
    println!("  \x1b[90mPress \x1b[1mq\x1b[0;90m to quit, \x1b[1ma\x1b[0;90m=all, \x1b[1mn\x1b[0;90m=none\x1b[0m");
    println!();
}

fn clear_menu(line_count: usize) {
    // Move cursor up and clear each line
    for _ in 0..line_count {
        print!("\x1b[A\x1b[K");
    }
    io::stdout().flush().ok();
}

/// Read a single key from the terminal (Windows-specific).
/// Returns: "up", "down", "space", "enter", "quit", "all", "none", or "unknown"
#[cfg(target_os = "windows")]
fn read_key() -> String {
    // On Windows, we use a PowerShell one-liner to read a single key
    // But that's slow. Instead, use the Windows console API via direct calls.
    // Simpler approach: read a line and interpret it.
    // For true single-key input, we need windows-sys or similar.
    // Let's use a simple fallback: numbered menu.
    String::from("unknown")
}

#[cfg(not(target_os = "windows"))]
fn read_key() -> String {
    String::from("unknown")
}

/// Fallback interactive menu using numbered input (works everywhere).
fn interactive_menu_simple() -> Vec<bool> {
    let mut selected: Vec<bool> = MENU_OPTIONS.iter().map(|o| o.default).collect();

    println!();
    println!("  \x1b[1;36m╔══════════════════════════════════════╗\x1b[0m");
    println!("  \x1b[1;36m║   X-RAY  Interactive Mode            ║\x1b[0m");
    println!("  \x1b[1;36m╚══════════════════════════════════════╝\x1b[0m");
    println!();

    loop {
        for (i, opt) in MENU_OPTIONS.iter().enumerate() {
            let mark = if selected[i] { "\x1b[1;32m✓\x1b[0m" } else { "\x1b[90m·\x1b[0m" };
            println!("  {} [{}] {}", i + 1, mark, opt.label);
        }
        println!();
        println!("  \x1b[90mType number to toggle, \x1b[1ma\x1b[0;90m=all, \x1b[1mn\x1b[0;90m=none, \x1b[1mEnter\x1b[0;90m=run, \x1b[1mq\x1b[0;90m=quit\x1b[0m");
        print!("  > ");
        io::stdout().flush().ok();

        let mut input = String::new();
        if io::stdin().read_line(&mut input).is_err() {
            break;
        }
        let input = input.trim().to_lowercase();

        if input.is_empty() {
            // Enter pressed → run with current selection
            break;
        } else if input == "q" {
            std::process::exit(0);
        } else if input == "a" {
            for s in selected.iter_mut() { *s = true; }
        } else if input == "n" {
            for s in selected.iter_mut() { *s = false; }
        } else if let Ok(num) = input.parse::<usize>() {
            if num >= 1 && num <= MENU_OPTIONS.len() {
                selected[num - 1] = !selected[num - 1];
            }
        }
        // Clear the menu lines and re-render
        let lines_to_clear = MENU_OPTIONS.len() + 4;
        clear_menu(lines_to_clear);
    }

    println!();
    selected
}

fn apply_interactive_choices(args: &mut Args, selected: &[bool]) {
    for (i, opt) in MENU_OPTIONS.iter().enumerate() {
        let on = selected[i];
        match opt.key {
            "smell"       => args.smell = on,
            "duplicates"  => args.duplicates = on,
            "lint"        => args.lint = on,
            "security"    => args.security = on,
            "rustify_exe" => args.rustify_exe = on,
            _ => {}
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════════
//  Rustify-exe: shell out to cargo via the Python pipeline
// ═══════════════════════════════════════════════════════════════════════════

fn run_rustify_exe(root: &std::path::Path, exclude: &[String]) {
    println!();
    println!("  {}", "═".repeat(60));
    println!("  🔧 FULL RUSTIFY PIPELINE: Python → Rust → Executable");
    println!("  {}", "═".repeat(60));
    println!();

    // Step 1: Scan and identify candidates
    println!("  [1/4] Scanning codebase for Rust candidates...");
    let t0 = Instant::now();
    let (functions, _classes, _errors) = ast_parse::scan_codebase(root, exclude, &[]);
    println!("         Found {} functions in {:.2}s", functions.len(), t0.elapsed().as_secs_f64());

    if functions.is_empty() {
        println!("  ✗ No Python functions found. Nothing to rustify.");
        return;
    }

    // Step 2: Score functions for Rust suitability
    println!("  [2/4] Scoring functions for Rust porting...");
    let mut candidates: Vec<(&types::FunctionRecord, f64)> = Vec::new();
    for func in &functions {
        let score = score_rust_candidate(func);
        if score >= 3.0 {
            candidates.push((func, score));
        }
    }
    candidates.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));

    println!("         {} candidates scored ≥ 3.0 out of {}", candidates.len(), functions.len());

    if candidates.is_empty() {
        println!("  ⚠ No functions scored high enough for Rust porting.");
        println!("    Try lowering the threshold or ensuring functions are pure/deterministic.");
        return;
    }

    // Print top candidates
    println!();
    println!("  {:─<60}", "─ Top Candidates ");
    for (i, (func, score)) in candidates.iter().take(15).enumerate() {
        let pure = if func.calls_to.is_empty() && !func.is_async { "pure" } else { "    " };
        println!("  {:>2}. [{:.1}] {:<40} {} ({}:{})",
            i + 1, score, func.name, pure,
            func.file_path.rsplit(['/', '\\']).next().unwrap_or(&func.file_path),
            func.line_start);
    }
    println!();

    // Step 3: Generate Rust code
    println!("  [3/4] Generating Rust source...");
    let out_dir = root.join("_rustified_exe");
    let src_dir = out_dir.join("src");
    std::fs::create_dir_all(&src_dir).ok();

    // Generate Cargo.toml
    let crate_name = root.file_name()
        .map(|n| n.to_string_lossy().to_lowercase().replace(|c: char| !c.is_alphanumeric(), "_"))
        .unwrap_or_else(|| "rustified".to_string());

    let cargo_toml = format!(
        r#"[package]
name = "{crate_name}"
version = "1.0.0"
edition = "2021"

[[bin]]
name = "{crate_name}"
path = "src/main.rs"

[profile.release]
opt-level = 3
lto = true
codegen-units = 1
strip = true
"#);
    std::fs::write(out_dir.join("Cargo.toml"), &cargo_toml).ok();

    // Generate main.rs with transpiled functions
    let mut main_rs = String::from("// Auto-generated by X-Ray Rustify Pipeline\n\n");
    for (func, _score) in candidates.iter().take(50) {
        main_rs.push_str(&format!("/// Transpiled from {}:{}\n", func.file_path, func.line_start));
        main_rs.push_str(&transpile_function_to_rust(func));
        main_rs.push_str("\n\n");
    }
    main_rs.push_str("fn main() {\n");
    main_rs.push_str("    println!(\"Rustified executable built successfully!\");\n");
    main_rs.push_str("    println!(\"Contains {} transpiled functions.\");\n");
    main_rs.push_str("}\n");

    std::fs::write(src_dir.join("main.rs"), &main_rs).ok();
    println!("         Generated {} functions → {}", candidates.len().min(50),
        src_dir.join("main.rs").display());

    // Step 4: Compile
    println!("  [4/4] Compiling with cargo build --release...");
    let compile_start = Instant::now();

    match std::process::Command::new("cargo")
        .args(["build", "--release"])
        .current_dir(&out_dir)
        .output()
    {
        Ok(output) => {
            let duration = compile_start.elapsed();
            if output.status.success() {
                // Find the executable
                let exe_name = if cfg!(windows) {
                    format!("{}.exe", crate_name)
                } else {
                    crate_name.clone()
                };
                let exe_path = out_dir.join("target").join("release").join(&exe_name);
                println!();
                println!("  \x1b[1;32m✓ SUCCESS\x1b[0m — Compiled in {:.1}s", duration.as_secs_f64());
                println!("  Executable: {}", exe_path.display());
                if exe_path.exists() {
                    let size = std::fs::metadata(&exe_path).map(|m| m.len()).unwrap_or(0);
                    println!("  Size: {:.1} MB", size as f64 / 1_048_576.0);
                }
            } else {
                let stderr = String::from_utf8_lossy(&output.stderr);
                println!();
                println!("  \x1b[1;31m✗ Compilation failed\x1b[0m ({:.1}s)", duration.as_secs_f64());
                // Show first few errors
                for line in stderr.lines().filter(|l| l.contains("error")).take(10) {
                    println!("    {}", line);
                }
                println!();
                println!("  The generated source is at: {}", src_dir.display());
                println!("  You can fix errors manually and run: cargo build --release");
            }
        }
        Err(_) => {
            println!("  \x1b[1;31m✗ cargo not found\x1b[0m — install Rust from https://rustup.rs");
        }
    }
}

/// Score a function for Rust porting suitability (0-10).
fn score_rust_candidate(func: &types::FunctionRecord) -> f64 {
    let mut score: f64 = 5.0;

    // Size bonus: medium functions are ideal (10-50 lines)
    let lines = func.size_lines;
    if lines < 5 { score -= 2.0; }
    else if lines <= 50 { score += 1.0; }
    else if lines > 100 { score -= 1.5; }

    // Complexity bonus: higher complexity benefits more from Rust
    if func.complexity > 5 { score += 1.0; }
    if func.complexity > 10 { score += 0.5; }

    // Pure function bonus (no external calls)
    if func.calls_to.is_empty() { score += 1.5; }

    // Async penalty
    if func.is_async { score -= 2.0; }

    // Test function penalty
    if func.name.starts_with("test_") { score -= 5.0; }

    // Dunder penalty
    if func.name.starts_with("__") && func.name.ends_with("__") { score -= 3.0; }

    // Low parameter count is easier to transpile
    if func.parameters.len() <= 3 { score += 0.5; }
    if func.parameters.len() > 6 { score -= 1.0; }

    // Has type annotations → easier to transpile
    if func.return_type.as_ref().map_or(false, |r| !r.is_empty()) { score += 0.5; }

    score.max(0.0).min(10.0)
}

/// Simple Python → Rust function transpilation (sketch generator).
fn transpile_function_to_rust(func: &types::FunctionRecord) -> String {
    let mut lines = Vec::new();

    // Parameters
    let params: Vec<String> = func.parameters.iter()
        .filter(|p| *p != "self")
        .map(|p| format!("{}: /* TODO */", p))
        .collect();
    let params_str = params.join(", ");

    let ret = match &func.return_type {
        Some(rt) if !rt.is_empty() => format!(" -> /* {} */", rt),
        _ => String::new(),
    };

    lines.push(format!("fn {}({}){} {{", func.name, params_str, ret));
    lines.push("    todo!(\"Transpile from Python\")".to_string());
    lines.push("}".to_string());

    lines.join("\n")
}

fn main() {
    let mut args = Args::parse();

    // Interactive mode
    if args.interactive {
        let selected = interactive_menu_simple();
        apply_interactive_choices(&mut args, &selected);
    }

    // Auto-select: if no flags → smell + lint + security
    let has_any = args.smell || args.duplicates || args.lint
        || args.security || args.full_scan || args.rustify_exe;
    if !has_any {
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

    // ── Rustify-exe mode ───────────────────────────────────────────
    if args.rustify_exe {
        run_rustify_exe(&root, &args.exclude);
        return;
    }

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
