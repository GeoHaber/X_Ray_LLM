//! Graph analysis — circular calls, coupling metrics, unused imports.
//! Rust port of analyzers/graph.py.
//!
//! Since we cannot use Python AST from Rust, this uses regex-based heuristics
//! for function definitions and calls in Python files.

use regex::Regex;
use std::collections::{HashMap, HashSet};
use walkdir::WalkDir;

use crate::constants::SKIP_DIRS;

// ── helpers ──────────────────────────────────────────────────────────────────

fn fwd(p: &str) -> String {
    p.replace('\\', "/")
}

fn walk_py(directory: &str) -> Vec<(std::path::PathBuf, String)> {
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
        if !entry.file_type().is_file() {
            continue;
        }
        let path = entry.path().to_path_buf();
        if path.extension().and_then(|e| e.to_str()) != Some("py") {
            continue;
        }
        let rel = path
            .strip_prefix(directory)
            .unwrap_or(&path)
            .to_string_lossy()
            .to_string();
        result.push((path, rel));
    }
    result
}

// ── circular calls ───────────────────────────────────────────────────────────

#[derive(Debug, Clone, serde::Serialize)]
struct FuncInfo {
    name: String,
    file: String,
    line: usize,
    calls: Vec<String>,
}

/// Detect circular call chains (function-level).
pub fn detect_circular_calls(directory: &str) -> serde_json::Value {
    let func_re = Regex::new(r"^\s*(?:async\s+)?def\s+(\w+)").unwrap();
    let call_re = Regex::new(r"\b(\w+)\s*\(").unwrap();

    let mut funcs: HashMap<String, FuncInfo> = HashMap::new();
    let mut name_to_keys: HashMap<String, Vec<String>> = HashMap::new();

    for (fpath, rel) in walk_py(directory) {
        let content = match std::fs::read_to_string(&fpath) {
            Ok(c) => c,
            Err(_) => continue,
        };
        let lines: Vec<&str> = content.lines().collect();
        let mut current_func: Option<(String, usize, HashSet<String>)> = None;
        let rel_fwd = fwd(&rel);

        for (i, line) in lines.iter().enumerate() {
            if let Some(caps) = func_re.captures(line) {
                // Save previous function
                if let Some((name, lineno, calls)) = current_func.take() {
                    let key = format!("{}::{}", rel_fwd, name);
                    let mut call_list: Vec<String> = calls.into_iter().collect();
                    call_list.retain(|c| c != &name); // no direct recursion
                    name_to_keys.entry(name.clone()).or_default().push(key.clone());
                    funcs.insert(
                        key,
                        FuncInfo {
                            name,
                            file: rel_fwd.clone(),
                            line: lineno,
                            calls: call_list,
                        },
                    );
                }
                let fname = caps[1].to_string();
                current_func = Some((fname, i + 1, HashSet::new()));
            } else if let Some((_, _, ref mut calls)) = current_func {
                for caps in call_re.captures_iter(line) {
                    calls.insert(caps[1].to_string());
                }
            }
        }
        // flush last function
        if let Some((name, lineno, calls)) = current_func.take() {
            let key = format!("{}::{}", rel_fwd, name);
            let mut call_list: Vec<String> = calls.into_iter().collect();
            call_list.retain(|c| c != &name);
            name_to_keys.entry(name.clone()).or_default().push(key.clone());
            funcs.insert(
                key,
                FuncInfo {
                    name,
                    file: rel_fwd.clone(),
                    line: lineno,
                    calls: call_list,
                },
            );
        }
    }

    // Build adjacency
    let mut adj: HashMap<String, HashSet<String>> = HashMap::new();
    for (key, info) in &funcs {
        for callee in &info.calls {
            if let Some(ckeys) = name_to_keys.get(callee) {
                for ck in ckeys {
                    if ck != key {
                        adj.entry(key.clone()).or_default().insert(ck.clone());
                    }
                }
            }
        }
    }

    // Detect recursive functions
    let mut recursive: Vec<serde_json::Value> = Vec::new();
    let call_re2 = Regex::new(r"\b(\w+)\s*\(").unwrap();
    for (fpath, rel) in walk_py(directory) {
        let content = match std::fs::read_to_string(&fpath) {
            Ok(c) => c,
            Err(_) => continue,
        };
        let lines: Vec<&str> = content.lines().collect();
        let mut current_func_name: Option<(String, usize)> = None;
        let rel_fwd = fwd(&rel);
        for (i, line) in lines.iter().enumerate() {
            if let Some(caps) = func_re.captures(line) {
                current_func_name = Some((caps[1].to_string(), i + 1));
            } else if let Some((ref fname, lineno)) = current_func_name {
                for caps in call_re2.captures_iter(line) {
                    if &caps[1] == fname {
                        recursive.push(serde_json::json!({
                            "function": fname,
                            "file": rel_fwd,
                            "line": lineno,
                        }));
                        current_func_name = None;
                        break;
                    }
                }
            }
        }
    }

    // Simple cycle detection via DFS (cap at 50 cycles)
    let mut cycles: Vec<serde_json::Value> = Vec::new();
    let keys: Vec<String> = funcs.keys().cloned().collect();
    let mut visited_global: HashSet<String> = HashSet::new();

    fn dfs(
        start: &str,
        current: &str,
        path: &mut Vec<String>,
        on_stack: &mut HashSet<String>,
        adj: &HashMap<String, HashSet<String>>,
        funcs: &HashMap<String, FuncInfo>,
        visited_global: &HashSet<String>,
        cycles: &mut Vec<serde_json::Value>,
    ) {
        if cycles.len() >= 50 {
            return;
        }
        on_stack.insert(current.to_string());
        path.push(current.to_string());
        if let Some(neighbours) = adj.get(current) {
            for nb in neighbours {
                if nb == start && path.len() >= 2 {
                    let mut chain: Vec<String> =
                        path.iter().filter_map(|k| funcs.get(k).map(|f| f.name.clone())).collect();
                    if let Some(f) = funcs.get(start) {
                        chain.push(f.name.clone());
                    }
                    let files: HashSet<String> =
                        path.iter().filter_map(|k| funcs.get(k).map(|f| f.file.clone())).collect();
                    let functions: Vec<serde_json::Value> =
                        path.iter().filter_map(|k| funcs.get(k).map(|f| serde_json::json!({
                            "name": f.name,
                            "file": f.file,
                            "line": f.line,
                        }))).collect();
                    cycles.push(serde_json::json!({
                        "chain": chain,
                        "length": chain.len() - 1,
                        "files": files.into_iter().collect::<Vec<_>>(),
                        "functions": functions,
                    }));
                } else if !on_stack.contains(nb.as_str()) && !visited_global.contains(nb.as_str()) {
                    dfs(start, nb, path, on_stack, adj, funcs, visited_global, cycles);
                }
            }
        }
        path.pop();
        on_stack.remove(current);
    }

    for key in &keys {
        if !visited_global.contains(key) && cycles.len() < 50 {
            dfs(
                key,
                key,
                &mut Vec::new(),
                &mut HashSet::new(),
                &adj,
                &funcs,
                &visited_global,
                &mut cycles,
            );
            visited_global.insert(key.clone());
        }
    }

    // Hub functions (high fan-in AND fan-out)
    let mut fan_in: HashMap<String, usize> = HashMap::new();
    let mut fan_out: HashMap<String, usize> = HashMap::new();
    for (key, nbs) in &adj {
        *fan_out.entry(key.clone()).or_insert(0) = nbs.len();
        for nb in nbs {
            *fan_in.entry(nb.clone()).or_insert(0) += 1;
        }
    }
    let mut hubs: Vec<serde_json::Value> = Vec::new();
    for (key, info) in &funcs {
        let fi = fan_in.get(key).copied().unwrap_or(0);
        let fo = fan_out.get(key).copied().unwrap_or(0);
        if fi >= 3 && fo >= 3 {
            hubs.push(serde_json::json!({
                "name": info.name,
                "file": info.file,
                "line": info.line,
                "fan_in": fi,
                "fan_out": fo,
                "score": fi * fo,
            }));
        }
    }
    hubs.sort_by(|a, b| {
        b["score"].as_u64().unwrap_or(0).cmp(&a["score"].as_u64().unwrap_or(0))
    });

    let total_edges: usize = adj.values().map(|s| s.len()).sum();

    serde_json::json!({
        "circular_calls": &cycles[..std::cmp::min(cycles.len(), 30)],
        "total_cycles": cycles.len(),
        "recursive_functions": &recursive[..std::cmp::min(recursive.len(), 20)],
        "total_recursive": recursive.len(),
        "hub_functions": &hubs[..std::cmp::min(hubs.len(), 20)],
        "total_hubs": hubs.len(),
        "total_functions": funcs.len(),
        "total_edges": total_edges,
    })
}

// ── coupling metrics ─────────────────────────────────────────────────────────

/// Compute coupling & cohesion metrics per module.
pub fn compute_coupling_metrics(directory: &str) -> serde_json::Value {
    let import_re = Regex::new(r"^\s*(?:import|from)\s+(\w+)").unwrap();
    let func_re = Regex::new(r"^\s*(?:async\s+)?def\s+\w+").unwrap();
    let class_re = Regex::new(r"^\s*class\s+\w+").unwrap();

    let mut modules: HashMap<String, serde_json::Value> = HashMap::new();
    let mut local_mods: HashSet<String> = HashSet::new();

    for (fpath, rel) in walk_py(directory) {
        let mod_name = fwd(&rel)
            .replace('/', ".")
            .trim_end_matches(".py")
            .trim_end_matches(".__init__")
            .to_string();
        local_mods.insert(mod_name.clone());
        let content = match std::fs::read_to_string(&fpath) {
            Ok(c) => c,
            Err(_) => continue,
        };
        let loc = content.lines().filter(|l| !l.trim().is_empty()).count();
        let func_count = content.lines().filter(|l| func_re.is_match(l)).count();
        let class_count = content.lines().filter(|l| class_re.is_match(l)).count();
        let mut imports: HashSet<String> = HashSet::new();
        for line in content.lines() {
            if let Some(caps) = import_re.captures(line) {
                imports.insert(caps[1].to_string());
            }
        }
        modules.insert(
            mod_name.clone(),
            serde_json::json!({
                "name": mod_name,
                "file": fwd(&rel),
                "loc": loc,
                "func_count": func_count,
                "class_count": class_count,
                "imports": imports.iter().cloned().collect::<Vec<_>>(),
                "imported_by": Vec::<String>::new(),
            }),
        );
    }

    // Resolve local imports
    let mut imported_by: HashMap<String, Vec<String>> = HashMap::new();
    for (mod_name, data) in &modules {
        if let Some(imports) = data["imports"].as_array() {
            for imp in imports {
                if let Some(target) = imp.as_str() {
                    if local_mods.contains(target) && target != mod_name {
                        imported_by.entry(target.to_string()).or_default().push(mod_name.clone());
                    }
                }
            }
        }
    }

    let mut results: Vec<serde_json::Value> = Vec::new();
    for (mod_name, data) in &modules {
        let raw_imports: Vec<String> = data["imports"]
            .as_array()
            .map(|a| a.iter().filter_map(|i| i.as_str().map(String::from)).collect())
            .unwrap_or_default();
        let local_imports: Vec<String> = raw_imports.iter()
            .filter(|i| local_mods.contains(i.as_str()))
            .cloned()
            .collect();
        let ce = local_imports.len();
        let ib = imported_by.get(mod_name).cloned().unwrap_or_default();
        let ca = ib.len();
        let instability = if ca + ce > 0 {
            (ce as f64) / ((ca + ce) as f64)
        } else {
            0.5
        };
        let instability = (instability * 100.0).round() / 100.0;
        let func_count = data["func_count"].as_u64().unwrap_or(0);
        let cohesion = if func_count <= 3 { "high" } else if func_count <= 10 { "medium" } else { "low" };
        let health = if ca >= 5 && ce >= 5 {
            "god_module"
        } else if instability > 0.8 && ca >= 3 {
            "fragile"
        } else if ca == 0 && ce == 0 && data["loc"].as_u64().unwrap_or(0) > 20 {
            "isolated"
        } else if ce > 8 {
            "dependent"
        } else {
            "healthy"
        };
        let mut sorted_imports = local_imports.clone();
        sorted_imports.sort();
        let mut sorted_ib = ib.clone();
        sorted_ib.sort();
        results.push(serde_json::json!({
            "module": mod_name,
            "file": data["file"],
            "loc": data["loc"],
            "afferent_coupling": ca,
            "efferent_coupling": ce,
            "instability": instability,
            "cohesion": cohesion,
            "health": health,
            "func_count": data["func_count"],
            "class_count": data["class_count"],
            "imports": sorted_imports,
            "imported_by": sorted_ib,
        }));
    }
    results.sort_by(|a, b| {
        let sa = a["afferent_coupling"].as_u64().unwrap_or(0) + a["efferent_coupling"].as_u64().unwrap_or(0);
        let sb = b["afferent_coupling"].as_u64().unwrap_or(0) + b["efferent_coupling"].as_u64().unwrap_or(0);
        sb.cmp(&sa)
    });

    let total = results.len();
    let avg_instability = if total > 0 {
        (results.iter().map(|r| r["instability"].as_f64().unwrap_or(0.5)).sum::<f64>() / total as f64
            * 100.0)
            .round()
            / 100.0
    } else {
        0.0
    };

    // Health summary and categorized lists
    let mut health_summary: HashMap<&str, usize> = HashMap::new();
    for cat in &["healthy", "god_module", "fragile", "isolated", "dependent"] {
        health_summary.insert(cat, 0);
    }
    let mut god_modules = Vec::new();
    let mut fragile_modules = Vec::new();
    let mut isolated_modules = Vec::new();
    for r in &results {
        let h = r["health"].as_str().unwrap_or("healthy");
        *health_summary.entry(h).or_insert(0) += 1;
        match h {
            "god_module" => { if god_modules.len() < 10 { god_modules.push(r.clone()); } }
            "fragile" => { if fragile_modules.len() < 10 { fragile_modules.push(r.clone()); } }
            "isolated" => { if isolated_modules.len() < 10 { isolated_modules.push(r.clone()); } }
            _ => {}
        }
    }

    serde_json::json!({
        "modules": results,
        "total_modules": total,
        "health_summary": health_summary,
        "avg_instability": avg_instability,
        "god_modules": god_modules,
        "fragile_modules": fragile_modules,
        "isolated_modules": isolated_modules,
    })
}

/// Detect unused imports via regex heuristics.
pub fn detect_unused_imports(directory: &str) -> serde_json::Value {
    let import_re = Regex::new(r"^\s*(?:import\s+(\w+)|from\s+\S+\s+import\s+(.+))").unwrap();
    let mut issues: Vec<serde_json::Value> = Vec::new();

    for (fpath, rel) in walk_py(directory) {
        let content = match std::fs::read_to_string(&fpath) {
            Ok(c) => c,
            Err(_) => continue,
        };
        let lines: Vec<&str> = content.lines().collect();
        let mut imported: Vec<(String, usize)> = Vec::new();

        for (i, line) in lines.iter().enumerate() {
            if let Some(caps) = import_re.captures(line) {
                if let Some(m) = caps.get(1) {
                    imported.push((m.as_str().to_string(), i + 1));
                } else if let Some(m) = caps.get(2) {
                    for name in m.as_str().split(',') {
                        let name = name.trim().split(" as ").last().unwrap_or("").trim();
                        if !name.is_empty() && name != "*" {
                            imported.push((name.to_string(), i + 1));
                        }
                    }
                }
            }
        }

        for (name, line) in &imported {
            if name == "_" {
                continue;
            }
            // Check if name is used anywhere outside import lines
            let used = lines.iter().enumerate().any(|(i, l)| {
                if i + 1 == *line {
                    return false;
                }
                let trimmed = l.trim();
                if trimmed.starts_with("import ") || trimmed.starts_with("from ") {
                    return false;
                }
                l.contains(name.as_str())
            });
            if !used {
                issues.push(serde_json::json!({
                    "file": fwd(&rel),
                    "line": line,
                    "import_name": name,
                    "severity": "LOW",
                }));
            }
        }
    }

    issues.sort_by(|a, b| {
        let fa = a["file"].as_str().unwrap_or("");
        let fb = b["file"].as_str().unwrap_or("");
        fa.cmp(fb).then(
            a["line"].as_u64().unwrap_or(0).cmp(&b["line"].as_u64().unwrap_or(0)),
        )
    });

    // Compute files_with_unused and by_file
    let mut file_counts: HashMap<String, usize> = HashMap::new();
    for issue in &issues {
        if let Some(f) = issue["file"].as_str() {
            *file_counts.entry(f.to_string()).or_insert(0) += 1;
        }
    }
    let files_with_unused = file_counts.len();
    // Top 20 files by count, sorted descending
    let mut by_file_vec: Vec<(String, usize)> = file_counts.into_iter().collect();
    by_file_vec.sort_by(|a, b| b.1.cmp(&a.1));
    by_file_vec.truncate(20);
    let by_file: serde_json::Map<String, serde_json::Value> = by_file_vec
        .into_iter()
        .map(|(k, v)| (k, serde_json::Value::from(v)))
        .collect();

    serde_json::json!({
        "unused_imports": issues,
        "total_unused": issues.len(),
        "files_with_unused": files_with_unused,
        "by_file": by_file,
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

    #[test]
    fn test_fwd() {
        assert_eq!(fwd("a\\b"), "a/b");
    }

    // ── detect_circular_calls ───────────────────────────────────────

    #[test]
    fn test_circular_calls_shape() {
        let (_dir, path) = make_temp_project(&[("mod.py", "x = 1\n")]);
        let result = detect_circular_calls(&path);
        assert!(result.get("circular_calls").is_some());
        assert!(result.get("total_cycles").is_some());
        assert!(result.get("recursive_functions").is_some());
        assert!(result.get("total_recursive").is_some());
        assert!(result.get("hub_functions").is_some());
        assert!(result.get("total_functions").is_some());
        assert!(result.get("total_edges").is_some());
    }

    #[test]
    fn test_circular_calls_detects_cycle() {
        let code = "\
def alpha():
    beta()

def beta():
    alpha()
";
        let (_dir, path) = make_temp_project(&[("mod.py", code)]);
        let result = detect_circular_calls(&path);
        let cycles = result["circular_calls"].as_array().unwrap();
        assert!(!cycles.is_empty(), "Should detect circular call between alpha and beta");
        let first = &cycles[0];
        assert!(first.get("chain").is_some(), "Cycle should have chain");
        assert!(first.get("length").is_some(), "Cycle should have length");
        assert!(first.get("files").is_some(), "Cycle should have files");
        assert!(first.get("functions").is_some(), "Cycle should have functions array");
        let funcs = first["functions"].as_array().unwrap();
        assert!(!funcs.is_empty(), "functions array should not be empty");
        let f = &funcs[0];
        assert!(f.get("name").is_some());
        assert!(f.get("file").is_some());
        assert!(f.get("line").is_some());
    }

    #[test]
    fn test_circular_calls_no_cycle() {
        let code = "\
def first():
    second()

def second():
    return 42
";
        let (_dir, path) = make_temp_project(&[("mod.py", code)]);
        let result = detect_circular_calls(&path);
        let cycles = result["circular_calls"].as_array().unwrap();
        assert!(cycles.is_empty(), "Linear call chain should have no cycles");
    }

    #[test]
    fn test_circular_calls_detects_recursion() {
        let code = "\
def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)
";
        let (_dir, path) = make_temp_project(&[("mod.py", code)]);
        let result = detect_circular_calls(&path);
        let recursive = result["recursive_functions"].as_array().unwrap();
        assert!(!recursive.is_empty(), "Should detect recursive function");
        assert_eq!(recursive[0]["function"].as_str().unwrap(), "factorial");
    }

    // ── compute_coupling_metrics ────────────────────────────────────

    #[test]
    fn test_coupling_shape() {
        let (_dir, path) = make_temp_project(&[("mod.py", "x = 1\n")]);
        let result = compute_coupling_metrics(&path);
        assert!(result.get("modules").is_some());
        assert!(result.get("total_modules").is_some());
        assert!(result.get("health_summary").is_some());
        assert!(result.get("avg_instability").is_some());
        assert!(result.get("god_modules").is_some());
        assert!(result.get("fragile_modules").is_some());
        assert!(result.get("isolated_modules").is_some());
    }

    #[test]
    fn test_coupling_module_fields() {
        let code = "import os\n\ndef hello():\n    pass\n";
        let (_dir, path) = make_temp_project(&[("mod.py", code)]);
        let result = compute_coupling_metrics(&path);
        let modules = result["modules"].as_array().unwrap();
        assert!(!modules.is_empty());
        let m = &modules[0];
        assert!(m.get("module").is_some());
        assert!(m.get("file").is_some());
        assert!(m.get("loc").is_some());
        assert!(m.get("afferent_coupling").is_some());
        assert!(m.get("efferent_coupling").is_some());
        assert!(m.get("instability").is_some());
        assert!(m.get("cohesion").is_some());
        assert!(m.get("health").is_some());
        assert!(m.get("imports").is_some());
        assert!(m.get("imported_by").is_some());
    }

    #[test]
    fn test_coupling_cohesion_high() {
        // Fewer than 4 functions => cohesion should be "high"
        let code = "def a():\n    pass\n\ndef b():\n    pass\n";
        let (_dir, path) = make_temp_project(&[("mod.py", code)]);
        let result = compute_coupling_metrics(&path);
        let modules = result["modules"].as_array().unwrap();
        let m = &modules[0];
        assert_eq!(m["cohesion"].as_str().unwrap(), "high");
    }

    #[test]
    fn test_coupling_cohesion_low() {
        // >10 functions => cohesion should be "low"
        let funcs: String = (0..12).map(|i| format!("def func_{}():\n    pass\n\n", i)).collect();
        let (_dir, path) = make_temp_project(&[("mod.py", &funcs)]);
        let result = compute_coupling_metrics(&path);
        let modules = result["modules"].as_array().unwrap();
        let m = &modules[0];
        assert_eq!(m["cohesion"].as_str().unwrap(), "low");
    }

    #[test]
    fn test_coupling_health_summary_keys() {
        let (_dir, path) = make_temp_project(&[("mod.py", "x = 1\n")]);
        let result = compute_coupling_metrics(&path);
        let hs = &result["health_summary"];
        assert!(hs.get("healthy").is_some());
        assert!(hs.get("god_module").is_some());
        assert!(hs.get("fragile").is_some());
        assert!(hs.get("isolated").is_some());
        assert!(hs.get("dependent").is_some());
    }

    #[test]
    fn test_coupling_imported_by() {
        // module_a imports module_b => module_b.imported_by should contain module_a
        let code_a = "import module_b\n\ndef use_b():\n    module_b.do_thing()\n";
        let code_b = "def do_thing():\n    return 42\n";
        let (_dir, path) = make_temp_project(&[("module_a.py", code_a), ("module_b.py", code_b)]);
        let result = compute_coupling_metrics(&path);
        let modules = result["modules"].as_array().unwrap();
        let mb = modules.iter().find(|m| m["module"].as_str().unwrap().contains("module_b")).unwrap();
        let ib = mb["imported_by"].as_array().unwrap();
        let ib_strs: Vec<&str> = ib.iter().filter_map(|v| v.as_str()).collect();
        assert!(ib_strs.iter().any(|s| s.contains("module_a")),
            "module_b should be imported_by module_a");
    }

    // ── detect_unused_imports ───────────────────────────────────────

    #[test]
    fn test_unused_imports_shape() {
        let (_dir, path) = make_temp_project(&[("mod.py", "x = 1\n")]);
        let result = detect_unused_imports(&path);
        assert!(result.get("unused_imports").is_some());
        assert!(result.get("total_unused").is_some());
        assert!(result.get("files_with_unused").is_some());
        assert!(result.get("by_file").is_some());
    }

    #[test]
    fn test_unused_imports_detects_unused() {
        let code = "import os\nimport sys\n\ndef f():\n    return os.getcwd()\n";
        let (_dir, path) = make_temp_project(&[("mod.py", code)]);
        let result = detect_unused_imports(&path);
        let imports = result["unused_imports"].as_array().unwrap();
        let names: Vec<&str> = imports.iter().filter_map(|i| i["import_name"].as_str()).collect();
        assert!(names.contains(&"sys"), "sys is imported but never used");
        assert!(!names.contains(&"os"), "os IS used and should not appear");
    }

    #[test]
    fn test_unused_imports_from_import() {
        let code = "from collections import OrderedDict, defaultdict\n\nx = defaultdict(list)\n";
        let (_dir, path) = make_temp_project(&[("mod.py", code)]);
        let result = detect_unused_imports(&path);
        let imports = result["unused_imports"].as_array().unwrap();
        let names: Vec<&str> = imports.iter().filter_map(|i| i["import_name"].as_str()).collect();
        assert!(names.contains(&"OrderedDict"), "OrderedDict is unused");
        assert!(!names.contains(&"defaultdict"), "defaultdict IS used");
    }

    #[test]
    fn test_unused_imports_by_file() {
        let code = "import os\nimport sys\n\nx = 1\n";
        let (_dir, path) = make_temp_project(&[("mod.py", code)]);
        let result = detect_unused_imports(&path);
        assert!(result["files_with_unused"].as_u64().unwrap() >= 1);
        let by_file = result["by_file"].as_object().unwrap();
        assert!(!by_file.is_empty(), "by_file should have entries");
    }

    #[test]
    fn test_unused_imports_none_when_all_used() {
        let code = "import os\n\ndef f():\n    return os.getcwd()\n";
        let (_dir, path) = make_temp_project(&[("mod.py", code)]);
        let result = detect_unused_imports(&path);
        assert_eq!(result["total_unused"].as_u64().unwrap(), 0);
        assert_eq!(result["files_with_unused"].as_u64().unwrap(), 0);
    }
}
