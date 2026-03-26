//! Code smell detection — long functions, complexity, nesting, etc.
//! Rust port of analyzers/smells.py.
//!
//! Note: Since Rust doesn't have a Python AST parser, we use regex-based
//! heuristics to detect function boundaries, parameter counts, and nesting.

use regex::Regex;
use std::collections::HashMap;
use walkdir::WalkDir;

use crate::constants::SKIP_DIRS;

/// A detected code smell.
#[derive(Debug, Clone, serde::Serialize)]
pub struct SmellItem {
    pub file: String,
    pub line: usize,
    pub severity: String,
    pub smell: String,
    pub description: String,
    pub metric: f64,
}

/// Result of smell detection.
#[derive(Debug, Clone, serde::Serialize)]
pub struct SmellResult {
    pub smells: Vec<SmellItem>,
    pub total: usize,
    pub by_type: HashMap<String, usize>,
}

/// Detect code smells in Python files across a directory.
pub fn detect_code_smells(directory: &str) -> SmellResult {
    let mut smells = Vec::new();
    let func_re = Regex::new(r"^(\s*)(async\s+)?def\s+(\w+)\s*\(([^)]*)\)").unwrap();
    let class_re = Regex::new(r"^(\s*)class\s+(\w+)").unwrap();
    let magic_re = Regex::new(r"(?:^|[=<>+\-*/%,(\[{: ])(-?\d+\.?\d*)(?:\s|[,)\]};:]|$)").unwrap();

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
        let lines: Vec<&str> = content.lines().collect();
        let rel = path
            .strip_prefix(directory)
            .unwrap_or(path)
            .to_string_lossy()
            .replace('\\', "/");

        // Detect function-level smells
        let mut i = 0;
        while i < lines.len() {
            if let Some(caps) = func_re.captures(lines[i]) {
                let indent_len = caps[1].len();
                let func_name = &caps[3];
                let params_str = &caps[4];
                let start_line = i + 1; // 1-based

                // Count function lines (until next same-indent definition or less-indented line)
                let mut end = i + 1;
                while end < lines.len() {
                    let line = lines[end];
                    if line.trim().is_empty() {
                        end += 1;
                        continue;
                    }
                    let cur_indent = line.len() - line.trim_start().len();
                    if cur_indent <= indent_len && !line.trim().is_empty() {
                        // Check if this is the end of the function body
                        if func_re.is_match(lines[end]) || class_re.is_match(lines[end]) || cur_indent < indent_len {
                            break;
                        }
                        if cur_indent == indent_len && !lines[end].trim().starts_with('#') {
                            break;
                        }
                    }
                    end += 1;
                }
                let line_count = end - i;

                // Long function (>50 lines)
                if line_count > 50 {
                    smells.push(SmellItem {
                        file: rel.clone(),
                        line: start_line,
                        severity: "MEDIUM".into(),
                        smell: "long_function".into(),
                        description: format!("Function '{func_name}' is {line_count} lines (max: 50)"),
                        metric: line_count as f64,
                    });
                }

                // Too many parameters (>5)
                let param_count = if params_str.trim().is_empty() {
                    0
                } else {
                    let mut count = params_str.split(',').count();
                    // Subtract self/cls
                    let first = params_str.split(',').next().unwrap_or("").trim();
                    if first == "self" || first == "cls" {
                        count = count.saturating_sub(1);
                    }
                    count
                };
                if param_count > 5 {
                    smells.push(SmellItem {
                        file: rel.clone(),
                        line: start_line,
                        severity: "MEDIUM".into(),
                        smell: "too_many_params".into(),
                        description: format!(
                            "Function '{func_name}' has {param_count} parameters (max: 5)"
                        ),
                        metric: param_count as f64,
                    });
                }

                // Cyclomatic complexity (count branches in function body)
                let branch_re = Regex::new(
                    r"\b(if|elif|while|for|except|and|or)\b"
                ).unwrap();
                let mut complexity = 1usize;
                for j in i..end.min(lines.len()) {
                    complexity += branch_re.find_iter(lines[j]).count();
                }
                if complexity > 10 {
                    smells.push(SmellItem {
                        file: rel.clone(),
                        line: start_line,
                        severity: "HIGH".into(),
                        smell: "high_complexity".into(),
                        description: format!(
                            "Function '{func_name}' has cyclomatic complexity {complexity} (max: 10)"
                        ),
                        metric: complexity as f64,
                    });
                }

                // Deep nesting
                let max_depth = max_nesting(&lines[i..end.min(lines.len())], indent_len);
                if max_depth > 4 {
                    smells.push(SmellItem {
                        file: rel.clone(),
                        line: start_line,
                        severity: "MEDIUM".into(),
                        smell: "deep_nesting".into(),
                        description: format!(
                            "Function '{func_name}' has nesting depth {max_depth} (max: 4)"
                        ),
                        metric: max_depth as f64,
                    });
                }

                // Too many return statements
                let return_re = Regex::new(r"\breturn\b").unwrap();
                let mut returns = 0;
                for j in i..end.min(lines.len()) {
                    returns += return_re.find_iter(lines[j]).count();
                }
                if returns > 5 {
                    smells.push(SmellItem {
                        file: rel.clone(),
                        line: start_line,
                        severity: "LOW".into(),
                        smell: "too_many_returns".into(),
                        description: format!(
                            "Function '{func_name}' has {returns} return statements (max: 5)"
                        ),
                        metric: returns as f64,
                    });
                }
            }

            // God class detection
            if let Some(caps) = class_re.captures(lines[i]) {
                let indent_len = caps[1].len();
                let class_name = &caps[2];
                let start_line = i + 1;

                let mut end = i + 1;
                while end < lines.len() {
                    let line = lines[end];
                    if line.trim().is_empty() {
                        end += 1;
                        continue;
                    }
                    let cur_indent = line.len() - line.trim_start().len();
                    if cur_indent <= indent_len && !line.trim().is_empty() && end > i + 1 {
                        break;
                    }
                    end += 1;
                }
                let class_lines = end - i;

                // Count methods
                let method_count = (i..end)
                    .filter(|&j| func_re.is_match(lines[j]))
                    .count();

                if class_lines > 300 {
                    smells.push(SmellItem {
                        file: rel.clone(),
                        line: start_line,
                        severity: "MEDIUM".into(),
                        smell: "god_class".into(),
                        description: format!("Class '{class_name}' is {class_lines} lines (max: 300)"),
                        metric: class_lines as f64,
                    });
                }
                if method_count > 20 {
                    smells.push(SmellItem {
                        file: rel.clone(),
                        line: start_line,
                        severity: "MEDIUM".into(),
                        smell: "god_class".into(),
                        description: format!(
                            "Class '{class_name}' has {method_count} methods (max: 20)"
                        ),
                        metric: method_count as f64,
                    });
                }
            }

            // bare except
            {
                let trimmed = lines[i].trim();
                if trimmed == "except:" || trimmed.starts_with("except: ") {
                    smells.push(SmellItem {
                        file: rel.clone(),
                        line: i + 1,
                        severity: "HIGH".into(),
                        smell: "bare_except".into(),
                        description: "Bare except clause (catches all exceptions including SystemExit/KeyboardInterrupt)".into(),
                        metric: 1.0,
                    });
                }
            }

            // mutable default argument
            if func_re.is_match(lines[i]) {
                let line_str = lines[i];
                if line_str.contains("=[]") || line_str.contains("= []")
                    || line_str.contains("={}") || line_str.contains("= {}")
                {
                    smells.push(SmellItem {
                        file: rel.clone(),
                        line: i + 1,
                        severity: "HIGH".into(),
                        smell: "mutable_default".into(),
                        description: "Mutable default argument (list/dict) — shared across calls".into(),
                        metric: 1.0,
                    });
                }
            }

            // magic number
            {
                let trimmed = lines[i].trim();
                if !trimmed.starts_with('#') && !trimmed.starts_with("import ")
                    && !trimmed.starts_with("from ") && !trimmed.is_empty()
                {
                    for cap in magic_re.captures_iter(trimmed) {
                        let num_str = &cap[1];
                        // Ignore 0, 1, 2, -1
                        if let Ok(n) = num_str.parse::<f64>() {
                            if n.abs() > 2.0 {
                                smells.push(SmellItem {
                                    file: rel.clone(),
                                    line: i + 1,
                                    severity: "LOW".into(),
                                    smell: "magic_number".into(),
                                    description: format!("Magic number {num_str} — consider named constant"),
                                    metric: n,
                                });
                                break; // one per line
                            }
                        }
                    }
                }
            }

            i += 1;
        }
    }

    // Group by smell type
    let mut by_type: HashMap<String, usize> = HashMap::new();
    for s in &smells {
        *by_type.entry(s.smell.clone()).or_insert(0) += 1;
    }

    let total = smells.len();
    SmellResult {
        smells,
        total,
        by_type,
    }
}

/// Calculate max nesting depth in a block of lines.
fn max_nesting(lines: &[&str], base_indent: usize) -> usize {
    let nesting_re = Regex::new(r"^\s*(if|for|while|with|try|except)\b").unwrap();
    let mut max_depth = 0usize;

    for line in lines {
        if line.trim().is_empty() {
            continue;
        }
        if nesting_re.is_match(line) {
            let indent = line.len() - line.trim_start().len();
            let depth = if indent > base_indent {
                (indent - base_indent) / 4 // assume 4-space indent
            } else {
                0
            };
            max_depth = max_depth.max(depth);
        }
    }

    max_depth
}

/// Detect duplicate code blocks using line hashing (grouped format matching Python).
pub fn detect_duplicates(directory: &str) -> serde_json::Value {
    use sha2::{Digest, Sha256};
    let chunk_size = 6usize;
    let mut chunks: HashMap<String, Vec<(String, usize)>> = HashMap::new();

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

        let lines: Vec<&str> = content.lines().collect();
        let normalized: Vec<String> = lines
            .iter()
            .map(|l| l.trim().to_string())
            .filter(|l| !l.is_empty() && !l.starts_with('#'))
            .collect();

        for start in 0..normalized.len().saturating_sub(chunk_size) {
            let chunk: String = normalized[start..start + chunk_size].join("\n");
            let mut hasher = Sha256::new();
            hasher.update(chunk.as_bytes());
            let hash = format!("{:x}", hasher.finalize());
            chunks.entry(hash).or_default().push((rel.clone(), start + 1));
        }
    }

    let mut duplicate_groups: Vec<serde_json::Value> = Vec::new();
    let mut total_duplicated_blocks = 0usize;

    for (hash, locations) in &chunks {
        if locations.len() < 2 {
            continue;
        }
        // Filter out overlapping within same file
        let mut filtered: Vec<&(String, usize)> = Vec::new();
        for loc in locations {
            let dominated = filtered.iter().any(|(f, l)| {
                f == &loc.0 && (*l as isize - loc.1 as isize).unsigned_abs() < chunk_size
            });
            if !dominated {
                filtered.push(loc);
            }
        }
        if filtered.len() < 2 {
            continue;
        }
        let occurrences = filtered.len();
        total_duplicated_blocks += occurrences;
        let loc_items: Vec<serde_json::Value> = filtered
            .iter()
            .take(10)
            .map(|(f, l)| serde_json::json!({"file": f, "line": l}))
            .collect();
        duplicate_groups.push(serde_json::json!({
            "hash": hash,
            "occurrences": occurrences,
            "locations": loc_items,
            "lines": chunk_size,
        }));
    }

    // Sort by -occurrences, cap at 200
    duplicate_groups.sort_by(|a, b| {
        b["occurrences"].as_u64().unwrap_or(0).cmp(&a["occurrences"].as_u64().unwrap_or(0))
    });
    let total_groups = duplicate_groups.len();
    duplicate_groups.truncate(200);

    serde_json::json!({
        "duplicate_groups": duplicate_groups,
        "total_groups": total_groups,
        "total_duplicated_blocks": total_duplicated_blocks,
    })
}

/// Detect potentially dead (uncalled) functions.
pub fn detect_dead_functions(directory: &str) -> serde_json::Value {
    let func_def_re = Regex::new(r"^\s*(?:async\s+)?def\s+(\w+)").unwrap();
    let func_call_re = Regex::new(r"\b(\w+)\s*\(").unwrap();
    // Also detect attribute calls: obj.method() — captures "method"
    let attr_call_re = Regex::new(r"\.(\w+)\s*\(").unwrap();

    let exempt: std::collections::HashSet<&str> = [
        "main", "setUp", "tearDown", "setUpClass", "tearDownClass",
        "setUpModule", "tearDownModule",
        "__init__", "__enter__", "__exit__", "__str__", "__repr__",
        "__len__", "__iter__", "__next__", "__getitem__", "__setitem__",
        "__eq__", "__hash__", "__lt__", "__le__", "__gt__", "__ge__",
        "__add__", "__sub__", "__bool__", "__contains__", "__delitem__",
    ].iter().copied().collect();

    let exempt_prefixes = ["test_", "on_", "handle_", "do_", "setup_", "teardown_", "_"];

    let mut defined: HashMap<String, serde_json::Value> = HashMap::new();
    let mut called: std::collections::HashSet<String> = std::collections::HashSet::new();

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

        for (i, line) in content.lines().enumerate() {
            // Collect definitions
            if let Some(caps) = func_def_re.captures(line) {
                let name = caps[1].to_string();
                if exempt.contains(name.as_str()) {
                    continue;
                }
                if exempt_prefixes.iter().any(|p| name.starts_with(p)) {
                    continue;
                }
                // Estimate function length by scanning ahead
                let indent_len = line.len() - line.trim_start().len();
                let mut end = i + 1;
                let all_lines: Vec<&str> = content.lines().collect();
                while end < all_lines.len() {
                    let l = all_lines[end];
                    if l.trim().is_empty() {
                        end += 1;
                        continue;
                    }
                    let cur = l.len() - l.trim_start().len();
                    if cur <= indent_len {
                        break;
                    }
                    end += 1;
                }
                let line_count = end - i;
                // Skip tiny functions (< 5 lines) — matches Python
                if line_count < 5 {
                    continue;
                }
                defined.entry(name.clone()).or_insert_with(|| {
                    serde_json::json!({
                        "name": name,
                        "file": rel,
                        "line": i + 1,
                        "lines": line_count,
                    })
                });
            }

            // Collect calls (but skip def lines — "def foo()" is not a call)
            if !func_def_re.is_match(line) {
                for caps in func_call_re.captures_iter(line) {
                    called.insert(caps[1].to_string());
                }
                for caps in attr_call_re.captures_iter(line) {
                    called.insert(caps[1].to_string());
                }
            }
        }
    }

    let mut dead: Vec<&serde_json::Value> = defined
        .iter()
        .filter(|(name, _)| !called.contains(name.as_str()))
        .map(|(_, v)| v)
        .collect();

    dead.sort_by(|a, b| {
        let la = b["lines"].as_u64().unwrap_or(0);
        let lb = a["lines"].as_u64().unwrap_or(0);
        lb.cmp(&la)
    });

    serde_json::json!({
        "dead_functions": dead,
        "total_defined": defined.len(),
        "total_dead": dead.len(),
        "total_called": called.len(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    /// Create a temp project with files inside a clean "project" subdir
    /// (avoids dot-prefix tempdir names being filtered by WalkDir).
    fn make_temp_project(files: &[(&str, &str)]) -> (tempfile::TempDir, String) {
        let dir = tempfile::tempdir().unwrap();
        let project = dir.path().join("project");
        fs::create_dir_all(&project).unwrap();
        for (name, content) in files {
            let path = project.join(name);
            if let Some(parent) = path.parent() {
                fs::create_dir_all(parent).unwrap();
            }
            fs::write(&path, content).unwrap();
        }
        (dir, project.to_str().unwrap().to_string())
    }

    // ── detect_code_smells ──────────────────────────────────────────

    #[test]
    fn test_smells_long_function() {
        let body: String = (0..60).map(|i| format!("    x_{i} = {i}\n")).collect();
        let code = format!("def big_func(a):\n{}", body);
        let (_dir, path) = make_temp_project(&[("mod.py", &code)]);
        let result = detect_code_smells(&path);
        assert!(result.smells.iter().any(|s| s.smell == "long_function"),
            "Should detect long_function");
    }

    #[test]
    fn test_smells_too_many_params() {
        let code = "def many(a, b, c, d, e, f, g):\n    pass\n";
        let (_dir, path) = make_temp_project(&[("mod.py", code)]);
        let result = detect_code_smells(&path);
        assert!(result.smells.iter().any(|s| s.smell == "too_many_params"),
            "Should detect too_many_params");
    }

    #[test]
    fn test_smells_self_excluded_from_params() {
        let code = "def method(self, a, b, c):\n    pass\n";
        let (_dir, path) = make_temp_project(&[("mod.py", code)]);
        let result = detect_code_smells(&path);
        assert!(!result.smells.iter().any(|s| s.smell == "too_many_params"),
            "self should not count as param");
    }

    #[test]
    fn test_smells_bare_except() {
        let code = "def f():\n    try:\n        pass\n    except:\n        pass\n";
        let (_dir, path) = make_temp_project(&[("mod.py", code)]);
        let result = detect_code_smells(&path);
        assert!(result.smells.iter().any(|s| s.smell == "bare_except"),
            "Should detect bare_except");
    }

    #[test]
    fn test_smells_no_bare_except_on_specific() {
        let code = "def f():\n    try:\n        pass\n    except ValueError:\n        pass\n";
        let (_dir, path) = make_temp_project(&[("mod.py", code)]);
        let result = detect_code_smells(&path);
        assert!(!result.smells.iter().any(|s| s.smell == "bare_except"),
            "Specific except should NOT trigger bare_except");
    }

    #[test]
    fn test_smells_mutable_default_list() {
        let code = "def f(items=[]):\n    items.append(1)\n    return items\n";
        let (_dir, path) = make_temp_project(&[("mod.py", code)]);
        let result = detect_code_smells(&path);
        assert!(result.smells.iter().any(|s| s.smell == "mutable_default"),
            "Should detect mutable_default for list");
    }

    #[test]
    fn test_smells_mutable_default_dict() {
        let code = "def f(opts={}):\n    return opts\n";
        let (_dir, path) = make_temp_project(&[("mod.py", code)]);
        let result = detect_code_smells(&path);
        assert!(result.smells.iter().any(|s| s.smell == "mutable_default"),
            "Should detect mutable_default for dict");
    }

    #[test]
    fn test_smells_magic_number() {
        let code = "def f():\n    timeout = 3600\n    return timeout\n";
        let (_dir, path) = make_temp_project(&[("mod.py", code)]);
        let result = detect_code_smells(&path);
        assert!(result.smells.iter().any(|s| s.smell == "magic_number"),
            "Should detect magic_number for 3600");
    }

    #[test]
    fn test_smells_no_magic_for_small_nums() {
        let code = "def f():\n    x = 0\n    y = 1\n    z = 2\n    return x + y + z\n";
        let (_dir, path) = make_temp_project(&[("mod.py", code)]);
        let result = detect_code_smells(&path);
        assert!(!result.smells.iter().any(|s| s.smell == "magic_number"),
            "0, 1, 2 should NOT trigger magic_number");
    }

    #[test]
    fn test_smells_by_type_populated() {
        let code = "def f(items=[]):\n    try:\n        pass\n    except:\n        pass\n";
        let (_dir, path) = make_temp_project(&[("mod.py", code)]);
        let result = detect_code_smells(&path);
        assert!(!result.by_type.is_empty(), "by_type should be populated");
        assert_eq!(result.total, result.smells.len());
    }

    #[test]
    fn test_smells_clean_code_no_smells() {
        let code = "def greet(name):\n    return f'Hello {name}'\n";
        let (_dir, path) = make_temp_project(&[("mod.py", code)]);
        let result = detect_code_smells(&path);
        assert!(!result.smells.iter().any(|s| s.smell == "long_function"));
        assert!(!result.smells.iter().any(|s| s.smell == "too_many_params"));
    }

    // ── detect_duplicates ───────────────────────────────────────────

    #[test]
    fn test_duplicates_identical_blocks() {
        let block = "x = 1\ny = 2\nz = 3\na = 4\nb = 5\nc = 6\nd = 7\n";
        let code1 = format!("def f():\n{}", block);
        let code2 = format!("def g():\n{}", block);
        let (_dir, path) = make_temp_project(&[("a.py", &code1), ("b.py", &code2)]);
        let result = detect_duplicates(&path);
        let groups = result["duplicate_groups"].as_array().unwrap();
        assert!(!groups.is_empty(), "Should find duplicate group");
        let first = &groups[0];
        assert!(first["hash"].is_string(), "Group should have hash");
        assert!(first["occurrences"].as_u64().unwrap() >= 2);
        assert!(first["locations"].is_array());
        assert!(first["lines"].is_number());
    }

    #[test]
    fn test_duplicates_no_false_positive() {
        let (_dir, path) = make_temp_project(&[
            ("a.py", "def f():\n    return 1\n"),
            ("b.py", "def g():\n    return 2\n"),
        ]);
        let result = detect_duplicates(&path);
        let groups = result["duplicate_groups"].as_array().unwrap();
        assert!(groups.is_empty(), "Unique code should have no duplicates");
        assert_eq!(result["total_groups"].as_u64().unwrap(), 0);
    }

    #[test]
    fn test_duplicates_shape() {
        let (_dir, path) = make_temp_project(&[("a.py", "x = 1\n")]);
        let result = detect_duplicates(&path);
        assert!(result.get("duplicate_groups").is_some());
        assert!(result.get("total_groups").is_some());
        assert!(result.get("total_duplicated_blocks").is_some());
    }

    // ── detect_dead_functions ───────────────────────────────────────

    #[test]
    fn test_dead_detects_uncalled() {
        let code = "\
def big_unused(x):
    a = 1
    b = 2
    c = 3
    d = 4
    return a + b + c + d + x

def caller():
    a = 1
    b = 2
    c = 3
    d = 4
    return a + b + c + d
";
        let (_dir, path) = make_temp_project(&[("mod.py", code)]);
        let result = detect_dead_functions(&path);
        let dead: Vec<&str> = result["dead_functions"].as_array().unwrap()
            .iter().filter_map(|d| d["name"].as_str()).collect();
        assert!(dead.contains(&"big_unused"), "big_unused should be dead");
    }

    #[test]
    fn test_dead_excludes_called() {
        let code = "\
def helper(x):
    a = 1
    b = 2
    c = 3
    d = 4
    return a + b + c + d + x

def caller():
    a = 1
    b = 2
    c = 3
    d = 4
    return helper(a + b + c + d)
";
        let (_dir, path) = make_temp_project(&[("mod.py", code)]);
        let result = detect_dead_functions(&path);
        let dead: Vec<&str> = result["dead_functions"].as_array().unwrap()
            .iter().filter_map(|d| d["name"].as_str()).collect();
        assert!(!dead.contains(&"helper"), "called function should not be dead");
    }

    #[test]
    fn test_dead_skips_tiny_functions() {
        let code = "def tiny():\n    return 1\n\ndef main():\n    a=1\n    b=2\n    c=3\n    d=4\n    return a+b+c+d\n";
        let (_dir, path) = make_temp_project(&[("mod.py", code)]);
        let result = detect_dead_functions(&path);
        let dead: Vec<&str> = result["dead_functions"].as_array().unwrap()
            .iter().filter_map(|d| d["name"].as_str()).collect();
        assert!(!dead.contains(&"tiny"), "Tiny functions (<5 lines) should be skipped");
    }

    #[test]
    fn test_dead_skips_exempt_prefixes() {
        let code = "\
def test_something():
    a = 1
    b = 2
    c = 3
    d = 4
    return a + b + c + d

def _private_helper():
    a = 1
    b = 2
    c = 3
    d = 4
    return a + b + c + d
";
        let (_dir, path) = make_temp_project(&[("mod.py", code)]);
        let result = detect_dead_functions(&path);
        let dead: Vec<&str> = result["dead_functions"].as_array().unwrap()
            .iter().filter_map(|d| d["name"].as_str()).collect();
        assert!(!dead.contains(&"test_something"), "test_ prefix should be exempt");
        assert!(!dead.contains(&"_private_helper"), "_ prefix should be exempt");
    }

    #[test]
    fn test_dead_attribute_calls_count() {
        let code = "\
def process(data):
    a = 1
    b = 2
    c = 3
    d = 4
    return data + a + b + c + d

def caller():
    a = 1
    b = 2
    c = 3
    d = 4
    return obj.process(a + b + c + d)
";
        let (_dir, path) = make_temp_project(&[("mod.py", code)]);
        let result = detect_dead_functions(&path);
        let dead: Vec<&str> = result["dead_functions"].as_array().unwrap()
            .iter().filter_map(|d| d["name"].as_str()).collect();
        assert!(!dead.contains(&"process"), "Attribute call obj.process() should count");
    }

    #[test]
    fn test_dead_shape() {
        let (_dir, path) = make_temp_project(&[("mod.py", "x = 1\n")]);
        let result = detect_dead_functions(&path);
        assert!(result.get("dead_functions").is_some());
        assert!(result.get("total_defined").is_some());
        assert!(result.get("total_dead").is_some());
        assert!(result.get("total_called").is_some());
    }
}
