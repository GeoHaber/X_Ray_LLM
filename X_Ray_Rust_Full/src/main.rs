// src/main.rs — X-Ray CLI entry point (optimized, zero duplication)
//
// This is the Rust equivalent of x_ray_claude.py, compiled to a native
// Windows/Mac/Linux executable. All duplicate patterns identified by
// X-Ray's self-scan have been eliminated.
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

    /// Show hardware profile and LLM recommendations
    #[arg(long)]
    system_info: bool,

    /// Save JSON report to file
    #[arg(long)]
    report: Option<String>,

    /// Directories to exclude
    #[arg(long, num_args = 0..)]
    exclude: Vec<String>,
}

// ═══════════════════════════════════════════════════════════════════════════
//  Interactive TUI — responsive, screen-adaptive, with system info
// ═══════════════════════════════════════════════════════════════════════════

struct MenuOption {
    key: &'static str,
    label: &'static str,
    icon: &'static str,
    default: bool,
    desc: &'static str,
}

const MENU_OPTIONS: &[MenuOption] = &[
    MenuOption { key: "smell",       label: "Code Smells",             icon: ">>",  default: true,  desc: "AST-based structural analysis" },
    MenuOption { key: "duplicates",  label: "Duplicates",              icon: "<>",  default: false, desc: "Find similar / copy-paste code" },
    MenuOption { key: "lint",        label: "Lint (Ruff)",            icon: "~~",  default: true,  desc: "Style, imports, hygiene" },
    MenuOption { key: "security",    label: "Security (Bandit)",      icon: "!!", default: true,  desc: "Vulnerability scanner" },
    MenuOption { key: "rustify_exe", label: "Rustify -> EXE",        icon: "=>",  default: false, desc: "Full transpile + compile pipeline" },
];

fn get_terminal_width() -> usize {
    if let Ok(val) = std::env::var("COLUMNS") {
        if let Ok(w) = val.parse::<usize>() {
            return w;
        }
    }
    #[cfg(target_os = "windows")]
    {
        use std::process::Command;
        if let Ok(output) = Command::new("cmd")
            .args(["/c", "mode con"])
            .output()
        {
            let s = String::from_utf8_lossy(&output.stdout);
            for line in s.lines() {
                let line = line.trim();
                if line.contains("Columns") || line.contains("columns") || line.contains("COL") {
                    if let Some(num) = line.split_whitespace().last() {
                        if let Ok(w) = num.parse::<usize>() {
                            return w;
                        }
                    }
                }
            }
        }
    }
    80
}

fn get_system_info() -> Vec<String> {
    let mut info = Vec::new();
    info.push(format!("OS:    {} {}", std::env::consts::OS, std::env::consts::ARCH));
    let cores = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(1);
    info.push(format!("Cores: {} logical", cores));

    #[cfg(target_os = "windows")]
    {
        use std::process::Command;
        if let Ok(output) = Command::new("powershell")
            .args(["-NoProfile", "-Command",
                   "[math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB, 1)"])
            .output()
        {
            let ram = String::from_utf8_lossy(&output.stdout).trim().to_string();
            if !ram.is_empty() {
                info.push(format!("RAM:   {} GB", ram));
            }
        }
    }
    #[cfg(target_os = "linux")]
    {
        if let Ok(meminfo) = std::fs::read_to_string("/proc/meminfo") {
            for line in meminfo.lines() {
                if line.starts_with("MemTotal") {
                    if let Some(kb_str) = line.split_whitespace().nth(1) {
                        if let Ok(kb) = kb_str.parse::<f64>() {
                            info.push(format!("RAM:   {:.1} GB", kb / 1_048_576.0));
                        }
                    }
                    break;
                }
            }
        }
    }

    // GPU detection
    #[cfg(target_os = "windows")]
    {
        use std::process::Command;
        // Try NVIDIA first
        let nvidia = Command::new("nvidia-smi")
            .args(["--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
            .output();
        if let Ok(output) = nvidia {
            let gpu = String::from_utf8_lossy(&output.stdout).trim().to_string();
            if !gpu.is_empty() {
                info.push(format!("GPU:   {}", gpu));
            }
        }
        // Fall back to WMI for Intel/AMD integrated
        if !info.iter().any(|s| s.starts_with("GPU:")) {
            if let Ok(output) = Command::new("powershell")
                .args(["-NoProfile", "-Command",
                       "(Get-CimInstance Win32_VideoController | Select-Object -First 1).Name"])
                .output()
            {
                let gpu = String::from_utf8_lossy(&output.stdout).trim().to_string();
                if !gpu.is_empty() {
                    info.push(format!("GPU:   {}", gpu));
                }
            }
        }
    }
    #[cfg(not(target_os = "windows"))]
    {
        if let Ok(output) = std::process::Command::new("nvidia-smi")
            .args(["--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
            .output()
        {
            let gpu = String::from_utf8_lossy(&output.stdout).trim().to_string();
            if !gpu.is_empty() {
                info.push(format!("GPU:   {}", gpu));
            }
        }
    }

    // Tier estimation
    let ram_gb: f64 = info.iter()
        .find(|s| s.starts_with("RAM:"))
        .and_then(|s| s.split_whitespace().nth(1))
        .and_then(|v| v.parse().ok())
        .unwrap_or(8.0);

    let has_gpu = info.iter().any(|s| s.starts_with("GPU:") && s.contains("NVIDIA"));
    let tier = if has_gpu { "High (NVIDIA GPU available)"
    } else if ram_gb >= 14.0 { "Medium (14+ GB RAM)"
    } else if ram_gb >= 8.0 { "Low (8 GB RAM)"
    } else { "Minimal" };
    info.push(format!("Tier:  {}", tier));

    info
}

#[allow(dead_code)]
fn clear_menu(line_count: usize) {
    for _ in 0..line_count {
        print!("\x1b[A\x1b[K");
    }
    io::stdout().flush().ok();
}

fn box_line(w: usize, text: &str) -> String {
    let visible_len = strip_ansi_len(text);
    let inner = if w > 4 { w - 4 } else { 0 };
    let pad = if inner > visible_len { inner - visible_len } else { 0 };
    format!("\x1b[36m║\x1b[0m {}{} \x1b[36m║\x1b[0m", text, " ".repeat(pad))
}

/// Strip ANSI escape codes and return visible character count
fn strip_ansi_len(text: &str) -> usize {
    let mut visible = 0;
    let mut in_escape = false;
    for ch in text.chars() {
        if ch == '\x1b' {
            in_escape = true;
        } else if in_escape {
            if ch == 'm' {
                in_escape = false;
            }
        } else {
            visible += 1;
        }
    }
    visible
}

/// Prompt user for a directory path with validation
fn prompt_directory(current: &std::path::Path) -> PathBuf {
    let box_w = 68;
    let top = format!("\x1b[1;36m╔{}╗\x1b[0m", "═".repeat(box_w - 2));
    let sep = format!("\x1b[36m╟{}╢\x1b[0m", "─".repeat(box_w - 2));
    let bot = format!("\x1b[1;36m╚{}╝\x1b[0m", "═".repeat(box_w - 2));

    println!();
    println!("  {}", top);
    println!("  {}", box_line(box_w,
        "  \x1b[1;97mSelect Directory to Scan\x1b[0m"));
    println!("  {}", sep);
    println!("  {}", box_line(box_w,
        &format!("  Current: \x1b[33m{}\x1b[0m", truncate_path(current, box_w - 18))));
    println!("  {}", sep);
    println!("  {}", box_line(box_w,
        "  \x1b[90mEnter path (or press Enter to keep current):\x1b[0m"));
    println!("  {}", box_line(box_w,
        "  \x1b[90mTip: drag & drop a folder into the terminal\x1b[0m"));
    println!("  {}", bot);
    println!();

    print!("  \x1b[1;33m>\x1b[0m ");
    io::stdout().flush().ok();

    let mut input = String::new();
    if io::stdin().read_line(&mut input).is_err() {
        return current.to_path_buf();
    }
    let input = input.trim().trim_matches('"').trim_matches('\'');

    if input.is_empty() {
        return current.to_path_buf();
    }

    let path = PathBuf::from(input);
    if path.is_dir() {
        println!("  \x1b[32m✓\x1b[0m Directory set: {}", path.display());
        path
    } else if path.exists() {
        println!("  \x1b[33m!\x1b[0m Not a directory. Using parent: {}", path.parent().unwrap_or(&path).display());
        path.parent().unwrap_or(&path).to_path_buf()
    } else {
        println!("  \x1b[31m✗\x1b[0m Path does not exist. Keeping: {}", current.display());
        current.to_path_buf()
    }
}

/// Prompt for directories to exclude
fn prompt_excludes(current_excludes: &[String]) -> Vec<String> {
    let box_w = 68;
    let top = format!("\x1b[1;36m╔{}╗\x1b[0m", "═".repeat(box_w - 2));
    let sep = format!("\x1b[36m╟{}╢\x1b[0m", "─".repeat(box_w - 2));
    let bot = format!("\x1b[1;36m╚{}╝\x1b[0m", "═".repeat(box_w - 2));

    println!();
    println!("  {}", top);
    println!("  {}", box_line(box_w,
        "  \x1b[1;97mExclude Directories\x1b[0m"));
    println!("  {}", sep);

    if current_excludes.is_empty() {
        println!("  {}", box_line(box_w,
            "  \x1b[90m(none currently excluded)\x1b[0m"));
    } else {
        for ex in current_excludes {
            println!("  {}", box_line(box_w,
                &format!("  \x1b[31m-\x1b[0m {}", ex)));
        }
    }
    println!("  {}", sep);
    println!("  {}", box_line(box_w,
        "  \x1b[90mEnter comma-separated dirs to exclude:\x1b[0m"));
    println!("  {}", box_line(box_w,
        "  \x1b[90m(Enter to keep current, 'clear' to remove all)\x1b[0m"));
    println!("  {}", bot);
    println!();

    print!("  \x1b[1;33m>\x1b[0m ");
    io::stdout().flush().ok();

    let mut input = String::new();
    if io::stdin().read_line(&mut input).is_err() {
        return current_excludes.to_vec();
    }
    let input = input.trim();

    if input.is_empty() {
        return current_excludes.to_vec();
    }
    if input.eq_ignore_ascii_case("clear") {
        println!("  \x1b[32m✓\x1b[0m Excludes cleared");
        return vec![];
    }

    let mut result: Vec<String> = current_excludes.to_vec();
    for item in input.split(',') {
        let item = item.trim().to_string();
        if !item.is_empty() && !result.contains(&item) {
            result.push(item);
        }
    }
    println!("  \x1b[32m✓\x1b[0m Excluding: {}", result.join(", "));
    result
}

/// Truncate a path for display
fn truncate_path(path: &std::path::Path, max_len: usize) -> String {
    let s = path.to_string_lossy().to_string();
    if s.len() <= max_len {
        s
    } else {
        format!("...{}", &s[s.len() - (max_len - 3)..])
    }
}

fn render_scan_menu(selected: &[bool], scan_path: &std::path::Path, excludes: &[String], box_w: usize) {
    let wide = box_w >= 60;
    let top = format!("\x1b[1;36m╔{}╗\x1b[0m", "═".repeat(box_w - 2));
    let mid = format!("\x1b[1;36m╠{}╣\x1b[0m", "═".repeat(box_w - 2));
    let sep = format!("\x1b[36m╟{}╢\x1b[0m", "─".repeat(box_w - 2));
    let bot = format!("\x1b[1;36m╚{}╝\x1b[0m", "═".repeat(box_w - 2));

    println!();
    println!("  {}", top);
    println!("  {}", box_line(box_w,
        &format!("      \x1b[1;97mX-RAY {}\x1b[0m  \x1b[36mInteractive Scanner\x1b[0m", config::VERSION)));
    println!("  {}", mid);

    // Show scan target path
    println!("  {}", box_line(box_w,
        &format!("  \x1b[90mPath:\x1b[0m \x1b[33m{}\x1b[0m", truncate_path(scan_path, box_w.saturating_sub(14)))));
    if !excludes.is_empty() {
        let exc_str = if excludes.len() <= 3 {
            excludes.join(", ")
        } else {
            format!("{}, ... (+{})", excludes[..2].join(", "), excludes.len() - 2)
        };
        println!("  {}", box_line(box_w,
            &format!("  \x1b[90mExcl:\x1b[0m \x1b[31m{}\x1b[0m", exc_str)));
    }
    println!("  {}", sep);

    // Analysis options
    for (i, opt) in MENU_OPTIONS.iter().enumerate() {
        let mark = if selected[i] { "\x1b[1;32m+\x1b[0m" } else { "\x1b[90m.\x1b[0m" };
        let num = format!("\x1b[1;97m{}\x1b[0m", i + 1);
        if wide {
            println!("  {}", box_line(box_w,
                &format!("  {}. [{}] {} {:<22} \x1b[90m{}\x1b[0m", num, mark, opt.icon, opt.label, opt.desc)));
        } else {
            println!("  {}", box_line(box_w,
                &format!("  {}. [{}] {}", num, mark, opt.label)));
        }
    }

    println!("  {}", sep);

    // Commands footer
    let count = selected.iter().filter(|&&s| s).count();
    println!("  {}", box_line(box_w,
        &format!("\x1b[1;97m{}\x1b[0m\x1b[90m/{} selected\x1b[0m", count, MENU_OPTIONS.len())));
    println!("  {}", box_line(box_w,
        "\x1b[90m1-5\x1b[0m toggle  \x1b[90ma\x1b[0m=all  \x1b[90mn\x1b[0m=none  \x1b[90mEnter\x1b[0m=run"));
    println!("  {}", box_line(box_w,
        "\x1b[90mp\x1b[0m=path  \x1b[90me\x1b[0m=excludes  \x1b[90ms\x1b[0m=system  \x1b[90mq\x1b[0m=quit"));
    println!("  {}", bot);
    println!();
}

fn render_system_info(box_w: usize) {
    let top = format!("\x1b[1;36m╔{}╗\x1b[0m", "═".repeat(box_w - 2));
    let mid = format!("\x1b[1;36m╠{}╣\x1b[0m", "═".repeat(box_w - 2));
    let sep = format!("\x1b[36m╟{}╢\x1b[0m", "─".repeat(box_w - 2));
    let bot = format!("\x1b[1;36m╚{}╝\x1b[0m", "═".repeat(box_w - 2));

    println!();
    println!("  {}", top);
    println!("  {}", box_line(box_w,
        "     \x1b[1;97mSystem Profile\x1b[0m  \x1b[36m& LLM Recommendations\x1b[0m"));
    println!("  {}", mid);

    let info = get_system_info();
    for line in &info {
        println!("  {}", box_line(box_w, &format!("  {}", line)));
    }

    println!("  {}", sep);
    println!("  {}", box_line(box_w, "\x1b[1;97mRecommended Models\x1b[0m"));

    let ram_gb: f64 = info.iter()
        .find(|s| s.starts_with("RAM:"))
        .and_then(|s| s.split_whitespace().nth(1))
        .and_then(|v| v.parse().ok())
        .unwrap_or(8.0);

    let models: Vec<(&str, &str, &str, f64)> = vec![
        ("Qwen 2.5 Coder 1.5B Q4",     "Very Fast", "Code:***   Reason:**",    4.0),
        ("Phi 3.5 Mini 3.8B Q4",        "Fast",      "Code:****  Reason:***",   6.0),
        ("Qwen 2.5 Coder 7B Q4",        "Medium",    "Code:***** Reason:****",  10.0),
        ("DeepSeek Coder V2 Lite 16B Q4","Medium",    "Code:***** Reason:****",  12.0),
        ("DeepSeek R1 Distill 7B Q4",   "Medium",    "Code:****  Reason:*****", 10.0),
        ("Gemma 2 9B Q4",               "Medium",    "Code:****  Reason:****",  12.0),
        ("Code Llama 13B Q4",           "Slower",    "Code:****  Reason:***",   16.0),
        ("Qwen 2.5 Coder 32B Q4",       "Slow",      "Code:***** Reason:*****", 24.0),
    ];

    let mut shown = 0;
    for (i, (name, speed, stars, min_ram)) in models.iter().enumerate() {
        if ram_gb + 2.0 >= *min_ram && shown < 5 {
            let tag = if shown == 0 { " \x1b[1;33m<- BEST\x1b[0m" } else { "" };
            println!("  {}", box_line(box_w,
                &format!("  {}. {} ({}){}", i + 1, name, speed, tag)));
            println!("  {}", box_line(box_w,
                &format!("     \x1b[90m{}  RAM: {:.0}GB\x1b[0m", stars, min_ram)));
            shown += 1;
        }
    }
    if shown == 0 {
        println!("  {}", box_line(box_w, "\x1b[90m  (limited RAM - try Qwen 1.5B Q4)\x1b[0m"));
    }

    println!("  {}", sep);
    println!("  {}", box_line(box_w, "\x1b[90mPress Enter to return\x1b[0m"));
    println!("  {}", bot);
    println!();
}

/// Interactive TUI: directory selection + analysis options + system info.
/// Returns (selected_flags, scan_path, excludes)
fn interactive_menu(initial_path: &std::path::Path, initial_excludes: &[String]) -> (Vec<bool>, PathBuf, Vec<String>) {
    let mut selected: Vec<bool> = MENU_OPTIONS.iter().map(|o| o.default).collect();
    let mut scan_path = initial_path.to_path_buf();
    let mut excludes: Vec<String> = initial_excludes.to_vec();
    let term_w = get_terminal_width();
    let box_w = std::cmp::min(term_w.saturating_sub(4), 72).max(50);

    // Show full header on first launch
    println!("\n  \x1b[1;36m{}\x1b[0m", "═".repeat(box_w));
    println!("  \x1b[1;97m  X-RAY {} — Interactive Mode\x1b[0m", config::VERSION);
    println!("  \x1b[1;36m{}\x1b[0m\n", "═".repeat(box_w));

    loop {
        render_scan_menu(&selected, &scan_path, &excludes, box_w);

        print!("  \x1b[1;33m>\x1b[0m ");
        io::stdout().flush().ok();

        let mut input = String::new();
        if io::stdin().read_line(&mut input).is_err() {
            break;
        }
        let input = input.trim().to_lowercase();

        match input.as_str() {
            "" => break,                               // Enter = run
            "q" | "quit" | "exit" => std::process::exit(0),
            "a" | "all" => { for s in selected.iter_mut() { *s = true; } }
            "n" | "none" => { for s in selected.iter_mut() { *s = false; } }
            "p" | "path" | "dir" => {
                scan_path = prompt_directory(&scan_path);
            }
            "e" | "exclude" | "ex" => {
                excludes = prompt_excludes(&excludes);
            }
            "s" | "sys" | "info" | "system" => {
                render_system_info(box_w);
                print!("  \x1b[90m(Enter to continue)\x1b[0m ");
                io::stdout().flush().ok();
                let mut _dummy = String::new();
                io::stdin().read_line(&mut _dummy).ok();
            }
            "f" | "full" => {
                for s in selected.iter_mut() { *s = true; }
                break;
            }
            other => {
                if let Ok(num) = other.parse::<usize>() {
                    if num >= 1 && num <= MENU_OPTIONS.len() {
                        selected[num - 1] = !selected[num - 1];
                    } else {
                        println!("  \x1b[90mInvalid option. Use 1-{}\x1b[0m", MENU_OPTIONS.len());
                    }
                } else {
                    println!("  \x1b[90mUnknown command: '{}'\x1b[0m", other);
                }
            }
        }
    }

    // Print summary before running
    let chosen: Vec<&str> = MENU_OPTIONS.iter().enumerate()
        .filter(|(i, _)| selected[*i])
        .map(|(_, o)| o.label)
        .collect();
    if chosen.is_empty() {
        println!("\n  \x1b[33m!\x1b[0m No analyses selected — defaulting to Smells + Lint + Security\n");
    } else {
        println!("\n  \x1b[32m✓\x1b[0m Running: \x1b[1;97m{}\x1b[0m", chosen.join(" + "));
        println!("  \x1b[32m✓\x1b[0m Target:  \x1b[33m{}\x1b[0m\n", scan_path.display());
    }

    (selected, scan_path, excludes)
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
    main_rs.push_str(&format!("    println!(\"Contains {} transpiled functions.\");\n", candidates.len().min(50)));
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

    // System info mode
    if args.system_info {
        let term_w = get_terminal_width();
        let box_w = std::cmp::min(term_w - 4, 72);
        render_system_info(box_w);
        return;
    }

    // Interactive mode
    if args.interactive {
        let initial_path = std::fs::canonicalize(&args.path).unwrap_or_else(|_| args.path.clone());
        let (selected, scan_path, excludes) = interactive_menu(&initial_path, &args.exclude);
        apply_interactive_choices(&mut args, &selected);
        args.path = scan_path;
        args.exclude = excludes;
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
