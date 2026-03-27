//! PM Dashboard — Risk Heatmap, Module Cards, Confidence Meter,
//! Sprint Batches, Architecture Map, Call Graph, Project Review.
//! Rust transpilation of analyzers/pm_dashboard.py.

use regex::Regex;
use std::collections::{HashMap, HashSet};
use std::process::Command;
use walkdir::WalkDir;

use crate::analyzers::detection::generate_test_stubs;
use crate::analyzers::format_check::check_format;
use crate::analyzers::health::{check_project_health, check_release_readiness};
use crate::analyzers::smells::{detect_code_smells, detect_dead_functions, detect_duplicates};
use crate::constants::SKIP_DIRS;

/// Forward-slash normaliser.
fn fwd(p: &str) -> String {
    p.replace('\\', "/")
}

/// Walk Python files, yielding (path, relative_path).
fn walk_py(directory: &str) -> Vec<(std::path::PathBuf, String)> {
    let mut results = Vec::new();
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
            .replace('\\', "/");
        results.push((path, rel));
    }
    results
}

/// Composite risk score per file — combines scanner findings, smells, duplicates, git churn.
/// Transpiled from pm_dashboard.py::compute_risk_heatmap().
pub fn compute_risk_heatmap(directory: &str, findings: &[serde_json::Value]) -> serde_json::Value {
    let smells_result = detect_code_smells(directory);
    let dups_result = detect_duplicates(directory);

    // Git churn (best-effort)
    let mut churn_map: HashMap<String, u32> = HashMap::new();
    if let Ok(output) = Command::new("git")
        .args(["log", "--since=90.days", "--name-only", "--pretty=format:"])
        .current_dir(directory)
        .output()
    {
        if output.status.success() {
            let stdout = String::from_utf8_lossy(&output.stdout);
            for line in stdout.lines() {
                let line = line.trim();
                if !line.is_empty() {
                    *churn_map.entry(line.to_string()).or_insert(0) += 1;
                }
            }
        }
    }

    // LOC per Python file
    let mut loc_map: HashMap<String, usize> = HashMap::new();
    for (path, rel) in walk_py(directory) {
        if let Ok(content) = std::fs::read_to_string(&path) {
            let loc = content.lines().filter(|l| !l.trim().is_empty()).count();
            loc_map.insert(rel, loc);
        }
    }

    // Accumulate per-file signals
    #[derive(Default)]
    struct RiskAccum {
        security: f64,
        quality: f64,
        smells: f64,
        churn: f64,
        duplicates: f64,
    }

    let mut risk: HashMap<String, RiskAccum> = HashMap::new();

    for f in findings {
        let rel = f.get("file").and_then(|v| v.as_str()).unwrap_or("");
        let sev = f.get("severity").and_then(|v| v.as_str()).unwrap_or("");
        let w = match sev {
            "HIGH" => 5.0,
            "MEDIUM" => 2.0,
            "LOW" => 0.5,
            _ => 1.0,
        };
        let entry = risk.entry(rel.to_string()).or_default();
        if f.get("rule_id").and_then(|v| v.as_str()).unwrap_or("").starts_with("SEC-") {
            entry.security += w;
        } else {
            entry.quality += w;
        }
    }

    if let Some(smells_arr) = smells_result.get("smells").and_then(|v| v.as_array()) {
        for s in smells_arr {
            let file = s.get("file").and_then(|v| v.as_str()).unwrap_or("");
            let sev = s.get("severity").and_then(|v| v.as_str()).unwrap_or("");
            let w = match sev {
                "HIGH" => 3.0,
                "MEDIUM" => 2.0,
                "LOW" => 1.0,
                _ => 1.0,
            };
            risk.entry(file.to_string()).or_default().smells += w;
        }
    }

    if let Some(groups) = dups_result.get("duplicate_groups").and_then(|v| v.as_array()) {
        for g in groups {
            if let Some(locations) = g.get("locations").and_then(|v| v.as_array()) {
                for loc in locations {
                    let file = loc.get("file").and_then(|v| v.as_str()).unwrap_or("");
                    risk.entry(file.to_string()).or_default().duplicates += 1.0;
                }
            }
        }
    }

    for (path, churn) in &churn_map {
        risk.entry(fwd(path)).or_default().churn = *churn as f64;
    }

    // Composite score per file
    let all_files: HashSet<String> = risk
        .keys()
        .chain(loc_map.keys())
        .cloned()
        .collect();

    let mut files: Vec<serde_json::Value> = Vec::new();
    for rel in &all_files {
        let r = risk.get(rel);
        let security = r.map(|r| r.security).unwrap_or(0.0);
        let quality = r.map(|r| r.quality).unwrap_or(0.0);
        let smells_v = r.map(|r| r.smells).unwrap_or(0.0);
        let churn = r.map(|r| r.churn).unwrap_or(0.0);
        let duplicates = r.map(|r| r.duplicates).unwrap_or(0.0);
        let score = security * 5.0 + quality * 2.0 + smells_v * 2.0 + churn * 3.0 + duplicates * 1.0;
        let loc = loc_map.get(rel).copied().unwrap_or(0);
        if score > 0.0 || loc > 0 {
            files.push(serde_json::json!({
                "file": rel,
                "risk_score": (score * 10.0).round() / 10.0,
                "loc": loc,
                "security": security,
                "quality": quality,
                "smells": smells_v,
                "churn": churn,
                "duplicates": duplicates,
            }));
        }
    }

    files.sort_by(|a, b| {
        let sa = a["risk_score"].as_f64().unwrap_or(0.0);
        let sb = b["risk_score"].as_f64().unwrap_or(0.0);
        sb.partial_cmp(&sa).unwrap_or(std::cmp::Ordering::Equal)
    });

    let max_risk = files
        .iter()
        .filter_map(|f| f["risk_score"].as_f64())
        .fold(1.0_f64, f64::max);

    let high_risk = files.iter().filter(|f| f["risk_score"].as_f64().unwrap_or(0.0) > max_risk * 0.6).count();
    let medium_risk = files
        .iter()
        .filter(|f| {
            let s = f["risk_score"].as_f64().unwrap_or(0.0);
            s > max_risk * 0.2 && s <= max_risk * 0.6
        })
        .count();
    let low_risk = files
        .iter()
        .filter(|f| f["risk_score"].as_f64().unwrap_or(0.0) <= max_risk * 0.2)
        .count();

    let total_files = files.len();
    files.truncate(300);

    serde_json::json!({
        "files": files,
        "total_files": total_files,
        "max_risk": (max_risk * 10.0).round() / 10.0,
        "high_risk": high_risk,
        "medium_risk": medium_risk,
        "low_risk": low_risk,
    })
}

/// Per-directory grade cards — module-level quality breakdown.
/// Transpiled from pm_dashboard.py::compute_module_cards().
pub fn compute_module_cards(directory: &str, findings: &[serde_json::Value]) -> serde_json::Value {
    let smells_result = detect_code_smells(directory);
    let test_result = generate_test_stubs(directory);

    #[derive(Default)]
    struct DirAccum {
        high: u32,
        medium: u32,
        low: u32,
        smells: u32,
        files: HashSet<String>,
        loc: usize,
        untested: u32,
    }

    let mut dirs: HashMap<String, DirAccum> = HashMap::new();

    for f in findings {
        let rel = f.get("file").and_then(|v| v.as_str()).unwrap_or("");
        let d = if rel.contains('/') {
            rel.rsplit_once('/').map(|(d, _)| d).unwrap_or(".")
        } else {
            "."
        };
        let entry = dirs.entry(d.to_string()).or_default();
        entry.files.insert(rel.to_string());
        match f.get("severity").and_then(|v| v.as_str()).unwrap_or("LOW") {
            "HIGH" => entry.high += 1,
            "MEDIUM" => entry.medium += 1,
            "LOW" => entry.low += 1,
            _ => {}
        }
    }

    if let Some(smells_arr) = smells_result.get("smells").and_then(|v| v.as_array()) {
        for s in smells_arr {
            let file = s.get("file").and_then(|v| v.as_str()).unwrap_or("");
            let d = if file.contains('/') {
                file.rsplit_once('/').map(|(d, _)| d).unwrap_or(".")
            } else {
                "."
            };
            let entry = dirs.entry(d.to_string()).or_default();
            entry.smells += 1;
            entry.files.insert(file.to_string());
        }
    }

    if let Some(stubs) = test_result.get("stubs").and_then(|v| v.as_array()) {
        for stub in stubs {
            let file = stub.get("file").and_then(|v| v.as_str()).unwrap_or("");
            let d = if file.contains('/') {
                file.rsplit_once('/').map(|(d, _)| d).unwrap_or(".")
            } else {
                "."
            };
            dirs.entry(d.to_string()).or_default().untested += 1;
        }
    }

    for (path, rel) in walk_py(directory) {
        let d = if rel.contains('/') {
            rel.rsplit_once('/').map(|(d, _)| d).unwrap_or(".")
        } else {
            "."
        };
        let entry = dirs.entry(d.to_string()).or_default();
        if let Ok(content) = std::fs::read_to_string(&path) {
            entry.loc += content.lines().filter(|l| !l.trim().is_empty()).count();
        }
        entry.files.insert(rel);
    }

    fn grade(h: u32, m: u32, low: u32, fc: usize) -> (&'static str, u32) {
        if fc == 0 {
            return ("?", 0);
        }
        let weighted = h as f64 * 5.0 + m as f64 * 2.0 + low as f64 * 0.5;
        let per100 = weighted / fc.max(1) as f64 * 100.0;
        if per100 <= 5.0 {
            ("A", 0f64.max(100.0 - per100) as u32)
        } else if per100 <= 15.0 {
            ("B", 0f64.max(100.0 - per100 * 0.8) as u32)
        } else if per100 <= 40.0 {
            ("C", 0f64.max(100.0 - per100 * 0.6) as u32)
        } else if per100 <= 80.0 {
            ("D", 20f64.max(100.0 - per100 * 0.5) as u32)
        } else {
            ("F", 5f64.max(100.0 - per100 * 0.4) as u32)
        }
    }

    let mut modules: Vec<serde_json::Value> = Vec::new();
    for (d, data) in &dirs {
        let fc = data.files.len();
        let (letter, score) = grade(data.high, data.medium, data.low, fc);
        modules.push(serde_json::json!({
            "module": d,
            "grade": letter,
            "score": score,
            "files": fc,
            "loc": data.loc,
            "high": data.high,
            "medium": data.medium,
            "low": data.low,
            "smells": data.smells,
            "untested": data.untested,
        }));
    }

    modules.sort_by(|a, b| {
        let sa = a["score"].as_u64().unwrap_or(0);
        let sb = b["score"].as_u64().unwrap_or(0);
        sa.cmp(&sb)
    });

    let total_modules = modules.len();
    serde_json::json!({
        "modules": modules,
        "total_modules": total_modules,
    })
}

/// Enhanced import graph with layers, circular deps, god modules, clusters.
/// Transpiled from pm_dashboard.py::compute_architecture_map().
pub fn compute_architecture_map(directory: &str) -> serde_json::Value {
    let mut nodes: HashMap<String, serde_json::Value> = HashMap::new();
    let mut edges: Vec<serde_json::Value> = Vec::new();
    let mut seen_edges: HashSet<String> = HashSet::new();
    let mut local_modules: HashSet<String> = HashSet::new();

    for (path, rel) in walk_py(directory) {
        let module = rel
            .replace('/', ".")
            .trim_end_matches(".py")
            .trim_end_matches(".__init__")
            .to_string();
        local_modules.insert(module.clone());
        let top_dir = if rel.contains('/') {
            rel.split('/').next().unwrap_or(".")
        } else {
            "."
        };
        let layer = if rel.to_lowercase().contains("test") {
            "test"
        } else if top_dir == "." {
            "app"
        } else {
            "lib"
        };
        let loc = std::fs::read_to_string(&path)
            .map(|c| c.lines().filter(|l| !l.trim().is_empty()).count())
            .unwrap_or(0);

        let label = module.split('.').last().unwrap_or(&module).to_string();
        nodes.insert(
            module.clone(),
            serde_json::json!({
                "id": module,
                "label": label,
                "file": rel,
                "external": false,
                "layer": layer,
                "imports_count": 0,
                "loc": loc,
                "dir": top_dir,
            }),
        );
    }

    for (path, rel) in walk_py(directory) {
        let module = rel
            .replace('/', ".")
            .trim_end_matches(".py")
            .trim_end_matches(".__init__")
            .to_string();

        let content = match std::fs::read_to_string(&path) {
            Ok(c) => c,
            Err(_) => continue,
        };

        for line in content.lines() {
            let line = line.trim();
            if !line.starts_with("import ") && !line.starts_with("from ") {
                continue;
            }
            let parts: Vec<&str> = line.split_whitespace().collect();
            let target = if parts.len() >= 2 {
                parts[1].split('.').next().unwrap_or("")
            } else {
                continue;
            };
            if target.is_empty() || target.starts_with('.') || target == "." {
                continue;
            }

            if !nodes.contains_key(target) {
                nodes.insert(
                    target.to_string(),
                    serde_json::json!({
                        "id": target,
                        "label": target,
                        "external": true,
                        "layer": "external",
                        "imports_count": 0,
                        "loc": 0,
                        "dir": "external",
                    }),
                );
            }

            if let Some(node) = nodes.get_mut(&module) {
                if let Some(count) = node.get("imports_count").and_then(|v| v.as_u64()) {
                    node["imports_count"] = serde_json::json!(count + 1);
                }
            }

            let ek = format!("{}->{}", module, target);
            if !seen_edges.contains(&ek) {
                seen_edges.insert(ek);
                edges.push(serde_json::json!({"from": module, "to": target}));
            }
        }
    }

    // Circular dependency detection (DFS on local modules)
    let mut adj: HashMap<String, HashSet<String>> = HashMap::new();
    for e in &edges {
        let from = e["from"].as_str().unwrap_or("");
        let to = e["to"].as_str().unwrap_or("");
        if local_modules.contains(from) && local_modules.contains(to) {
            adj.entry(from.to_string()).or_default().insert(to.to_string());
        }
    }

    let mut circular_deps: Vec<Vec<String>> = Vec::new();
    let mut visited: HashSet<String> = HashSet::new();

    fn dfs(
        node: &str,
        path: &mut Vec<String>,
        on_stack: &mut HashSet<String>,
        visited: &mut HashSet<String>,
        adj: &HashMap<String, HashSet<String>>,
        circular_deps: &mut Vec<Vec<String>>,
    ) {
        visited.insert(node.to_string());
        on_stack.insert(node.to_string());
        path.push(node.to_string());

        if let Some(neighbors) = adj.get(node) {
            for nb in neighbors {
                if !visited.contains(nb.as_str()) {
                    dfs(nb, path, on_stack, visited, adj, circular_deps);
                } else if on_stack.contains(nb.as_str()) {
                    if let Some(idx) = path.iter().position(|x| x == nb) {
                        let mut cycle: Vec<String> = path[idx..].to_vec();
                        cycle.push(nb.clone());
                        if cycle.len() <= 10 {
                            circular_deps.push(cycle);
                        }
                    }
                }
            }
        }

        path.pop();
        on_stack.remove(node);
    }

    let local_list: Vec<String> = local_modules.iter().cloned().collect();
    for m in &local_list {
        if !visited.contains(m.as_str()) {
            dfs(m, &mut Vec::new(), &mut HashSet::new(), &mut visited, &adj, &mut circular_deps);
        }
    }
    circular_deps.truncate(20);

    // God modules (many inbound local deps)
    let mut local_inbound: HashMap<String, u32> = HashMap::new();
    for e in &edges {
        let from = e["from"].as_str().unwrap_or("");
        let to = e["to"].as_str().unwrap_or("");
        if local_modules.contains(from) && local_modules.contains(to) {
            *local_inbound.entry(to.to_string()).or_insert(0) += 1;
        }
    }
    let mut god_modules: Vec<serde_json::Value> = local_inbound
        .iter()
        .filter(|(_, c)| **c >= 5)
        .map(|(m, c)| {
            let loc = nodes.get(m).and_then(|n| n.get("loc")).and_then(|v| v.as_u64()).unwrap_or(0);
            serde_json::json!({"module": m, "dependents": c, "loc": loc})
        })
        .collect();
    god_modules.sort_by(|a, b| {
        let da = b["dependents"].as_u64().unwrap_or(0);
        let db = a["dependents"].as_u64().unwrap_or(0);
        da.cmp(&db)
    });
    god_modules.truncate(10);

    // Clusters
    let mut clusters: HashMap<String, Vec<String>> = HashMap::new();
    for n in nodes.values() {
        let dir = n.get("dir").and_then(|v| v.as_str()).unwrap_or(".");
        clusters
            .entry(dir.to_string())
            .or_default()
            .push(n["id"].as_str().unwrap_or("").to_string());
    }

    // Layers
    let mut layers: HashMap<&str, Vec<String>> = HashMap::new();
    for n in nodes.values() {
        let layer = n.get("layer").and_then(|v| v.as_str()).unwrap_or("external");
        layers
            .entry(layer)
            .or_default()
            .push(n["id"].as_str().unwrap_or("").to_string());
    }

    serde_json::json!({
        "nodes": nodes.values().collect::<Vec<_>>(),
        "edges": edges,
        "layers": {
            "test": layers.get("test").cloned().unwrap_or_default(),
            "app": layers.get("app").cloned().unwrap_or_default(),
            "lib": layers.get("lib").cloned().unwrap_or_default(),
            "external": layers.get("external").cloned().unwrap_or_default(),
        },
        "circular_deps": circular_deps,
        "god_modules": god_modules,
        "clusters": clusters,
    })
}

/// AST-based call graph: who calls whom, entry points, leaf functions.
/// Transpiled from pm_dashboard.py::compute_call_graph().
/// Note: Uses regex-based approximation since Rust doesn't have a Python AST parser.
pub fn compute_call_graph(directory: &str) -> serde_json::Value {
    let func_re = Regex::new(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(").unwrap();
    let call_re = Regex::new(r"\b(\w+)\s*\(").unwrap();
    let decorator_re = Regex::new(r"@\w*\.?(route|get|post|put|delete|command|task|cli)").unwrap();

    #[derive(Default)]
    struct FuncInfo {
        name: String,
        file: String,
        line: usize,
        lines: usize,
        is_entry: bool,
        calls: Vec<String>,
        called_by: Vec<String>,
    }

    let mut functions: HashMap<String, FuncInfo> = HashMap::new();
    let mut name_to_keys: HashMap<String, Vec<String>> = HashMap::new();

    for (path, rel) in walk_py(directory) {
        let content = match std::fs::read_to_string(&path) {
            Ok(c) => c,
            Err(_) => continue,
        };
        let lines_vec: Vec<&str> = content.lines().collect();

        let mut i = 0;
        while i < lines_vec.len() {
            if let Some(caps) = func_re.captures(lines_vec[i]) {
                let fname = caps.get(1).map(|m| m.as_str()).unwrap_or("").to_string();
                let func_line = i + 1;

                // Check decorator on previous line
                let is_entry = fname == "main"
                    || (i > 0 && decorator_re.is_match(lines_vec[i - 1]));

                // Estimate function body
                let indent = lines_vec[i].len() - lines_vec[i].trim_start().len();
                let mut end = i + 1;
                for j in (i + 1)..lines_vec.len() {
                    let l = lines_vec[j];
                    if l.trim().is_empty() {
                        continue;
                    }
                    let l_indent = l.len() - l.trim_start().len();
                    if l_indent <= indent
                        && (l.trim_start().starts_with("def ")
                            || l.trim_start().starts_with("async def ")
                            || l.trim_start().starts_with("class "))
                    {
                        break;
                    }
                    end = j + 1;
                }
                let line_count = end - i;

                // Find calls within function body
                let mut fn_calls: Vec<String> = Vec::new();
                for j in (i + 1)..end.min(lines_vec.len()) {
                    for m in call_re.captures_iter(lines_vec[j]) {
                        let callee = m.get(1).map(|c| c.as_str()).unwrap_or("");
                        if !callee.is_empty()
                            && callee != &fname
                            && !["if", "for", "while", "with", "print", "range", "len", "str", "int", "float", "list", "dict", "set", "tuple", "type", "isinstance", "hasattr", "getattr", "setattr", "super"]
                                .contains(&callee)
                        {
                            fn_calls.push(callee.to_string());
                        }
                    }
                }

                let key = format!("{}::{}", fwd(&rel), fname);
                name_to_keys
                    .entry(fname.clone())
                    .or_default()
                    .push(key.clone());

                functions.insert(
                    key,
                    FuncInfo {
                        name: fname,
                        file: fwd(&rel),
                        line: func_line,
                        lines: line_count,
                        is_entry,
                        calls: fn_calls,
                        called_by: Vec::new(),
                    },
                );
            }
            i += 1;
        }
    }

    // Resolve edges
    let mut resolved_edges: Vec<serde_json::Value> = Vec::new();
    let keys: Vec<String> = functions.keys().cloned().collect();
    for key in &keys {
        let calls = functions[key].calls.clone();
        for callee_name in &calls {
            if let Some(callee_keys) = name_to_keys.get(callee_name) {
                for ck in callee_keys {
                    resolved_edges.push(serde_json::json!({"from": key, "to": ck}));
                    if let Some(callee_func) = functions.get_mut(ck) {
                        callee_func.called_by.push(key.clone());
                    }
                }
            }
        }
    }

    let entries: Vec<String> = functions
        .iter()
        .filter(|(_, v)| v.is_entry || v.called_by.is_empty())
        .map(|(k, _)| k.clone())
        .collect();

    let leaves: Vec<String> = functions
        .iter()
        .filter(|(_, v)| {
            !v.name.starts_with('_')
                && v.calls.iter().all(|c| !name_to_keys.contains_key(c))
        })
        .map(|(k, _)| k.clone())
        .collect();

    let mut nodes: Vec<serde_json::Value> = functions
        .iter()
        .map(|(k, d)| {
            serde_json::json!({
                "id": k,
                "name": d.name,
                "file": d.file,
                "line": d.line,
                "lines": d.lines,
                "is_entry": d.is_entry,
                "call_count": d.calls.len(),
                "caller_count": d.called_by.len(),
            })
        })
        .collect();
    nodes.truncate(500);
    resolved_edges.truncate(2000);

    serde_json::json!({
        "nodes": nodes,
        "edges": resolved_edges,
        "entries": &entries[..entries.len().min(50)],
        "leaves": &leaves[..leaves.len().min(50)],
        "total_functions": functions.len(),
        "total_edges": resolved_edges.len(),
    })
}

/// Release confidence synthesis — one number + narrative.
/// Transpiled from pm_dashboard.py::compute_confidence_meter().
pub fn compute_confidence_meter(directory: &str, findings: &[serde_json::Value]) -> serde_json::Value {
    let health = check_project_health(directory);
    let release = check_release_readiness(directory);
    let dead = detect_dead_functions(directory);
    let test = generate_test_stubs(directory);
    let smells = detect_code_smells(directory);
    let arch = compute_architecture_map(directory);

    let mut checks: Vec<serde_json::Value> = Vec::new();
    let mut score: u32 = 0;
    let mut max_score: u32 = 0;

    let mut add = |name: &str, passed: bool, weight: u32, detail: &str| {
        max_score += weight;
        if passed {
            score += weight;
        }
        checks.push(serde_json::json!({
            "name": name,
            "passed": passed,
            "weight": weight,
            "detail": detail,
        }));
    };

    let high_sec = findings
        .iter()
        .filter(|f| {
            f.get("severity").and_then(|v| v.as_str()) == Some("HIGH")
                && f.get("rule_id")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .starts_with("SEC-")
        })
        .count();
    add(
        "No critical security issues",
        high_sec == 0,
        20,
        &if high_sec > 0 {
            format!("{} HIGH security findings", high_sec)
        } else {
            "Clean".to_string()
        },
    );

    let high_total = findings
        .iter()
        .filter(|f| f.get("severity").and_then(|v| v.as_str()) == Some("HIGH"))
        .count();
    add(
        "No HIGH-severity findings",
        high_total == 0,
        10,
        &if high_total > 0 {
            format!("{} HIGH findings", high_total)
        } else {
            "Clean".to_string()
        },
    );

    let health_score = health.get("score").and_then(|v| v.as_u64()).unwrap_or(0);
    add(
        "Project health >= 70%",
        health_score >= 70,
        10,
        &format!("Health: {}%", health_score),
    );

    let cov = test.get("coverage_pct").and_then(|v| v.as_f64()).unwrap_or(0.0);
    add(
        "Test coverage >= 50%",
        cov >= 50.0,
        15,
        &format!("Coverage: {}%", cov),
    );

    let dc = dead.get("total_dead").and_then(|v| v.as_u64()).unwrap_or(0);
    add(
        "Minimal dead code (< 5)",
        dc < 5,
        5,
        &format!("{} dead functions", dc),
    );

    let hs = smells
        .get("smells")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter(|s| s.get("severity").and_then(|v| v.as_str()) == Some("HIGH"))
                .count()
        })
        .unwrap_or(0);
    add(
        "No HIGH code smells",
        hs == 0,
        10,
        &if hs > 0 {
            format!("{} HIGH smells", hs)
        } else {
            "Clean".to_string()
        },
    );

    let circ = arch
        .get("circular_deps")
        .and_then(|v| v.as_array())
        .map(|a| a.len())
        .unwrap_or(0);
    add(
        "No circular dependencies",
        circ == 0,
        10,
        &if circ > 0 {
            format!("{} circular deps", circ)
        } else {
            "Clean".to_string()
        },
    );

    let gods = arch
        .get("god_modules")
        .and_then(|v| v.as_array())
        .map(|a| a.len())
        .unwrap_or(0);
    add(
        "No god modules (>=5 dependents)",
        gods == 0,
        5,
        &if gods > 0 {
            format!("{} god modules", gods)
        } else {
            "Clean".to_string()
        },
    );

    let release_score = release.get("score").and_then(|v| v.as_u64()).unwrap_or(0);
    add(
        "Release readiness >= 70%",
        release_score >= 70,
        10,
        &format!("Readiness: {}%", release_score),
    );

    // Check formatting
    let fmt = check_format(directory);
    let all_formatted = fmt.get("all_formatted").and_then(|v| v.as_bool()).unwrap_or(false);
    let needs_format = fmt.get("needs_format").and_then(|v| v.as_u64()).unwrap_or(0);
    add(
        "Code formatting passes",
        all_formatted,
        5,
        &if !all_formatted {
            format!("{} files need formatting", needs_format)
        } else {
            "Clean".to_string()
        },
    );

    let confidence = if max_score > 0 {
        (score as f64 / max_score as f64 * 100.0).round() as u32
    } else {
        0
    };

    let mut top_risks: Vec<serde_json::Value> = checks
        .iter()
        .filter(|c| !c["passed"].as_bool().unwrap_or(true))
        .map(|c| {
            serde_json::json!({
                "name": c["name"],
                "detail": c["detail"],
                "weight": c["weight"],
            })
        })
        .collect();
    top_risks.sort_by(|a, b| {
        let wa = b["weight"].as_u64().unwrap_or(0);
        let wb = a["weight"].as_u64().unwrap_or(0);
        wa.cmp(&wb)
    });
    top_risks.truncate(5);

    let rec = if confidence >= 80 {
        "Good to ship. Minor items can be addressed post-release."
    } else if confidence >= 60 {
        "Address top risks before release. Focus on highest-weight items first."
    } else if confidence >= 40 {
        "Significant work needed. Prioritize security and test coverage."
    } else {
        "Not ready for release. Major structural issues need attention."
    };

    let passed = checks.iter().filter(|c| c["passed"].as_bool().unwrap_or(false)).count();
    let total = checks.len();

    serde_json::json!({
        "confidence": confidence,
        "checks": checks,
        "passed": passed,
        "total": total,
        "top_risks": top_risks,
        "recommendation": rec,
    })
}

/// Group all issues into sprint-sized action batches sorted by ROI.
/// Transpiled from pm_dashboard.py::compute_sprint_batches().
pub fn compute_sprint_batches(
    findings: &[serde_json::Value],
    smells: &[serde_json::Value],
) -> serde_json::Value {
    let mut items: Vec<serde_json::Value> = Vec::new();

    for f in findings {
        let rid = f.get("rule_id").and_then(|v| v.as_str()).unwrap_or("");
        let sev = f.get("severity").and_then(|v| v.as_str()).unwrap_or("LOW");
        let mins: u32 = if rid.starts_with("SEC-") {
            15
        } else if rid.starts_with("QUAL-") {
            5
        } else {
            10
        };
        let impact: u32 = match sev {
            "HIGH" => 10,
            "MEDIUM" => 4,
            "LOW" => 1,
            _ => 2,
        };
        let roi = (impact as f64 / mins.max(1) as f64 * 100.0).round() / 100.0;
        items.push(serde_json::json!({
            "type": "finding",
            "id": rid,
            "file": f.get("file").and_then(|v| v.as_str()).unwrap_or(""),
            "line": f.get("line").and_then(|v| v.as_u64()).unwrap_or(0),
            "severity": sev,
            "description": f.get("description").and_then(|v| v.as_str()).unwrap_or(""),
            "fix_hint": f.get("fix_hint").and_then(|v| v.as_str()).unwrap_or(""),
            "minutes": mins,
            "impact": impact,
            "roi": roi,
        }));
    }

    for s in smells {
        let sev = s.get("severity").and_then(|v| v.as_str()).unwrap_or("LOW");
        let impact: u32 = match sev {
            "HIGH" => 8,
            "MEDIUM" => 3,
            "LOW" => 1,
            _ => 2,
        };
        let roi = (impact as f64 / 15.0 * 100.0).round() / 100.0;
        let smell_name = s.get("smell").and_then(|v| v.as_str()).unwrap_or("");
        items.push(serde_json::json!({
            "type": "smell",
            "id": smell_name,
            "file": s.get("file").and_then(|v| v.as_str()).unwrap_or(""),
            "line": s.get("line").and_then(|v| v.as_u64()).unwrap_or(0),
            "severity": sev,
            "description": s.get("description").and_then(|v| v.as_str()).unwrap_or(""),
            "fix_hint": format!("Refactor: {}", smell_name.replace('_', " ")),
            "minutes": 15,
            "impact": impact,
            "roi": roi,
        }));
    }

    items.sort_by(|a, b| {
        let ra = b["roi"].as_f64().unwrap_or(0.0);
        let rb = a["roi"].as_f64().unwrap_or(0.0);
        ra.partial_cmp(&rb).unwrap_or(std::cmp::Ordering::Equal)
    });

    let mut batches = vec![
        serde_json::json!({"name": "Quick Wins (< 4h)", "items": [], "total_min": 0u32}),
        serde_json::json!({"name": "Sprint 1 (4-8h)", "items": [], "total_min": 0u32}),
        serde_json::json!({"name": "Sprint 2 (8-16h)", "items": [], "total_min": 0u32}),
        serde_json::json!({"name": "Backlog (16h+)", "items": [], "total_min": 0u32}),
    ];

    let mut running: u32 = 0;
    for item in &items {
        let mins = item["minutes"].as_u64().unwrap_or(0) as u32;
        running += mins;
        let idx = if running <= 240 {
            0
        } else if running <= 480 {
            1
        } else if running <= 960 {
            2
        } else {
            3
        };
        if let Some(batch_items) = batches[idx]["items"].as_array_mut() {
            if batch_items.len() < 100 {
                batch_items.push(item.clone());
            }
        }
        if let Some(total) = batches[idx]["total_min"].as_u64() {
            batches[idx]["total_min"] = serde_json::json!(total + mins as u64);
        }
    }

    let total_items = items.len();
    let mut cum = 0usize;
    let mut total_min_sum: u64 = 0;
    for b in &mut batches {
        let batch_count = b["items"].as_array().map(|a| a.len()).unwrap_or(0);
        cum += batch_count;
        let pct = if total_items > 0 {
            (cum as f64 / total_items as f64 * 100.0).round() as u32
        } else {
            0
        };
        let total_min = b["total_min"].as_u64().unwrap_or(0);
        total_min_sum += total_min;
        b["pct_resolved"] = serde_json::json!(pct);
        b["total_hours"] = serde_json::json!((total_min as f64 / 60.0 * 10.0).round() / 10.0);
        // Remove max_min from output (Python does `del b["max_min"]`)
    }

    let total_hours = (total_min_sum as f64 / 60.0 * 10.0).round() / 10.0;

    serde_json::json!({
        "batches": batches,
        "total_items": total_items,
        "total_hours": total_hours,
    })
}

/// Generate a comprehensive PM-style project review.
/// Transpiled from pm_dashboard.py::compute_project_review().
pub fn compute_project_review(
    directory: &str,
    findings: &[serde_json::Value],
    files_scanned: usize,
    smells: &[serde_json::Value],
    dead_functions: &[serde_json::Value],
    health: Option<&serde_json::Value>,
    satd: Option<&serde_json::Value>,
    duplicates: Option<&serde_json::Value>,
) -> serde_json::Value {
    let dir_path = std::path::Path::new(directory);
    let project_name = dir_path
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("unknown");

    // Severity breakdown
    let mut sev_counts: HashMap<&str, u32> = HashMap::new();
    sev_counts.insert("HIGH", 0);
    sev_counts.insert("MEDIUM", 0);
    sev_counts.insert("LOW", 0);
    for f in findings {
        let sev = f.get("severity").and_then(|v| v.as_str()).unwrap_or("LOW");
        *sev_counts.entry(sev).or_insert(0) += 1;
    }
    let total = sev_counts.values().sum::<u32>();
    let high = *sev_counts.get("HIGH").unwrap_or(&0);
    let medium = *sev_counts.get("MEDIUM").unwrap_or(&0);
    let low = *sev_counts.get("LOW").unwrap_or(&0);

    // Category breakdown
    let mut cat_counts: HashMap<String, u32> = HashMap::new();
    for f in findings {
        let rid = f.get("rule_id").and_then(|v| v.as_str()).unwrap_or("UNKNOWN");
        let cat = if rid.contains('-') {
            rid.split('-').next().unwrap_or(rid)
        } else {
            rid
        };
        *cat_counts.entry(cat.to_string()).or_insert(0) += 1;
    }

    // Score
    let deductions = high as f64 * 5.0 + medium as f64 * 2.0 + low as f64 * 0.5;
    let score = 0.0_f64.max(100.0_f64.min((100.0 - deductions).round()));
    let letter = if score >= 90.0 {
        "A"
    } else if score >= 75.0 {
        "B"
    } else if score >= 60.0 {
        "C"
    } else if score >= 40.0 {
        "D"
    } else {
        "F"
    };

    // Top hotspot files
    let mut file_issues: HashMap<String, (u32, u32, u32, u32)> = HashMap::new();
    for f in findings {
        let fp = f.get("file").and_then(|v| v.as_str()).unwrap_or("unknown");
        let entry = file_issues.entry(fp.to_string()).or_insert((0, 0, 0, 0));
        match f.get("severity").and_then(|v| v.as_str()).unwrap_or("LOW") {
            "HIGH" => entry.0 += 1,
            "MEDIUM" => entry.1 += 1,
            _ => entry.2 += 1,
        }
        entry.3 += 1;
    }
    let mut hotspots: Vec<(String, u32, u32, u32, u32)> = file_issues
        .into_iter()
        .map(|(f, (h, m, l, t))| (f, h, m, l, t))
        .collect();
    hotspots.sort_by(|a, b| b.1.cmp(&a.1).then(b.4.cmp(&a.4)));
    hotspots.truncate(15);

    // Recommendations
    let mut must_do: Vec<serde_json::Value> = Vec::new();
    let mut should_do: Vec<serde_json::Value> = Vec::new();
    let mut nice_to_have: Vec<serde_json::Value> = Vec::new();

    if high > 0 {
        must_do.push(serde_json::json!({
            "title": format!("Fix {} HIGH severity issues", high),
            "reason": "High severity findings indicate security vulnerabilities or critical reliability flaws that can lead to data breaches or system failures.",
            "effort": format!("{} min", high * 15),
            "impact": "Critical",
        }));
    }

    let sec_count = findings
        .iter()
        .filter(|f| {
            f.get("rule_id")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .starts_with("SEC-")
        })
        .count() as u32;

    if sec_count > 0 {
        must_do.push(serde_json::json!({
            "title": format!("Address {} security findings", sec_count),
            "reason": "Security issues must be resolved before any production release to prevent exploitation.",
            "effort": format!("{} min", sec_count * 20),
            "impact": "Critical",
        }));
    }

    if medium > 5 {
        should_do.push(serde_json::json!({
            "title": format!("Reduce {} MEDIUM severity issues", medium),
            "reason": "Medium issues degrade code quality and increase maintenance burden over time.",
            "effort": format!("{} min", medium * 10),
            "impact": "High",
        }));
    }

    if smells.len() > 5 {
        should_do.push(serde_json::json!({
            "title": format!("Refactor {} code smells", smells.len()),
            "reason": "Code smells increase complexity, make debugging harder, and slow down new feature development.",
            "effort": format!("{} min", smells.len() * 15),
            "impact": "Medium",
        }));
    }

    if dead_functions.len() > 3 {
        should_do.push(serde_json::json!({
            "title": format!("Remove {} dead functions", dead_functions.len()),
            "reason": "Dead code confuses developers and increases cognitive load without providing value.",
            "effort": format!("{} min", dead_functions.len() * 5),
            "impact": "Medium",
        }));
    }

    if let Some(dups) = duplicates {
        let dup_groups = dups.get("total_groups").and_then(|v| v.as_u64()).unwrap_or(0);
        if dup_groups > 0 {
            nice_to_have.push(serde_json::json!({
                "title": format!("Consolidate {} duplicate code groups", dup_groups),
                "reason": "Duplicate code increases maintenance burden and risk of inconsistent bug fixes.",
                "effort": format!("{} min", dup_groups * 20),
                "impact": "Medium",
            }));
        }
    }

    if low > 10 {
        nice_to_have.push(serde_json::json!({
            "title": format!("Clean up {} LOW severity items", low),
            "reason": "While individually minor, large numbers of low-severity issues signal declining code discipline.",
            "effort": format!("{} min", low * 5),
            "impact": "Low",
        }));
    }

    // Health flags
    let mut health_flags: HashMap<String, bool> = HashMap::new();
    if let Some(h) = health {
        if let Some(obj) = h.as_object() {
            for (k, v) in obj {
                if let Some(b) = v.as_bool() {
                    health_flags.insert(k.clone(), b);
                }
            }
        }
    }

    // Debt summary
    let debt_hours = satd
        .and_then(|s| s.get("total_hours"))
        .and_then(|v| v.as_f64())
        .unwrap_or(0.0);
    let debt_items = satd
        .and_then(|s| s.get("total_items"))
        .and_then(|v| v.as_u64())
        .unwrap_or(0);

    // Release readiness
    let blockers = high + sec_count;
    let release_ready = blockers == 0 && score >= 60.0;
    let release_status = if release_ready { "GO" } else { "NO-GO" };

    // Estimated total fix time
    let total_fix_min = high * 15 + medium * 10 + low * 5 + smells.len() as u32 * 15 + dead_functions.len() as u32 * 5;
    let total_fix_hours = (total_fix_min as f64 / 60.0 * 10.0).round() / 10.0;

    let dup_count = duplicates
        .and_then(|d| d.get("total_groups"))
        .and_then(|v| v.as_u64())
        .unwrap_or(0);

    serde_json::json!({
        "project_name": project_name,
        "directory": directory,
        "files_scanned": files_scanned,
        "score": score as u32,
        "letter": letter,
        "release_status": release_status,
        "release_ready": release_ready,
        "blockers": blockers,
        "severity": {"HIGH": high, "MEDIUM": medium, "LOW": low},
        "total_findings": total,
        "categories": cat_counts,
        "hotspots": hotspots.iter().map(|(f, h, m, l, t)| serde_json::json!({
            "file": f, "high": h, "medium": m, "low": l, "total": t,
        })).collect::<Vec<_>>(),
        "must_do": must_do,
        "should_do": should_do,
        "nice_to_have": nice_to_have,
        "health_flags": health_flags,
        "debt_hours": debt_hours,
        "debt_items": debt_items,
        "total_fix_hours": total_fix_hours,
        "smells_count": smells.len(),
        "dead_count": dead_functions.len(),
        "duplicates_count": dup_count,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_compute_sprint_batches_empty() {
        let result = compute_sprint_batches(&[], &[]);
        assert_eq!(result["total_items"].as_u64().unwrap(), 0);
        assert_eq!(result["batches"].as_array().unwrap().len(), 4);
    }

    #[test]
    fn test_compute_project_review_empty() {
        let tmp = tempfile::tempdir().unwrap();
        let result = compute_project_review(
            tmp.path().to_str().unwrap(),
            &[],
            0,
            &[],
            &[],
            None,
            None,
            None,
        );
        assert_eq!(result["score"].as_u64().unwrap(), 100);
        assert_eq!(result["letter"].as_str().unwrap(), "A");
    }
}
