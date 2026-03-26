//! Connection analyzer — map UI actions to backend handlers.
//! Rust port of analyzers/connections.py.

use regex::Regex;
use std::collections::{BTreeSet, HashMap};
use walkdir::WalkDir;

use crate::constants::SKIP_DIRS;

const FRONTEND_EXTS: &[&str] = &["js", "ts", "jsx", "tsx", "html", "vue", "svelte"];
const BACKEND_EXTS: &[&str] = &["py", "js", "ts"];

fn fwd(p: &str) -> String {
    p.replace('\\', "/")
}

fn normalize_route(url: &str) -> String {
    let url = url.split('?').next().unwrap_or(url);
    let url = url.trim_end_matches('/');
    let url = if url.is_empty() { "/" } else { url };
    let param_re = Regex::new(r"(?:<[^>]+>|:\w+|\{[^}]+\})").unwrap();
    param_re.replace_all(url, "_PARAM_").to_string()
}

/// Snap a byte index to the nearest valid char boundary (go backward).
fn floor_char_boundary(s: &str, mut idx: usize) -> usize {
    if idx >= s.len() { return s.len(); }
    while idx > 0 && !s.is_char_boundary(idx) { idx -= 1; }
    idx
}
/// Snap a byte index to the nearest valid char boundary (go forward).
fn ceil_char_boundary(s: &str, mut idx: usize) -> usize {
    if idx >= s.len() { return s.len(); }
    while idx < s.len() && !s.is_char_boundary(idx) { idx += 1; }
    idx
}

fn is_relative_api(url: &str) -> bool {
    if url.starts_with("http://") || url.starts_with("https://") || url.starts_with("//") {
        return false;
    }
    url.starts_with('/')
}

fn infer_method(context: &str, call_type: &str) -> String {
    let method_re = Regex::new(r#"(?i)(?:method|methods)\s*[:=]\s*['"\[]*\s*(GET|POST|PUT|DELETE|PATCH)"#).unwrap();
    if let Some(m) = method_re.captures(context) {
        return m[1].to_uppercase();
    }
    if call_type == "form_action" || call_type.contains("post") {
        return "POST".into();
    }
    "UNKNOWN".into()
}

fn walk_ext<'a>(directory: &'a str, exts: &'a [&str]) -> Vec<(std::path::PathBuf, String)> {
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
        let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("");
        if !exts.contains(&ext) {
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

/// Analyze UI-to-backend connections matching the Python shape.
pub fn analyze_connections(directory: &str) -> serde_json::Value {
    let fe_patterns: Vec<(Regex, &str)> = vec![
        (Regex::new(r#"fetch\(\s*['"]([\w/._\-?&=:]+)['"]\s*"#).unwrap(), "fetch"),
        (Regex::new(r#"axios\.(?:get|post|put|delete|patch)\(\s*['"]([\w/._\-?&=:]+)['"]\s*"#).unwrap(), "axios"),
        (Regex::new(r#"\$\.(?:ajax|get|post)\(\s*['"]([\w/._\-?&=:]+)['"]"#).unwrap(), "jquery"),
        (Regex::new(r#"api\(\s*['"]([\w/._\-?&=:]+)['"]"#).unwrap(), "api"),
        (Regex::new(r#"XMLHttpRequest[^;]*\.open\(\s*['"][^'"]*['"]\s*,\s*['"]([^'"]+)['"]"#).unwrap(), "xhr"),
        (Regex::new(r#"action\s*=\s*['"]([^'"]+)['"]"#).unwrap(), "form_action"),
        (Regex::new(r#"href\s*=\s*['](/api/[^']+)['"]"#).unwrap(), "href"),
    ];

    let be_patterns: Vec<(Regex, &str)> = vec![
        (Regex::new(r#"@\w+\.route\(\s*['"]([^'"]+)['"]"#).unwrap(), "flask"),
        (Regex::new(r#"@\w+\.(?:get|post|put|delete|patch)\(\s*['"]([^'"]+)['"]"#).unwrap(), "fastapi"),
        (Regex::new(r#"(?:^|,)\s*path\(\s*['"]([^'"]+)['"]"#).unwrap(), "django"),
        (Regex::new(r#"re_path\(\s*['"]([^'"]+)['"]"#).unwrap(), "django"),
        (Regex::new(r#"(?:app|router)\.(?:get|post|put|delete|patch|all|use)\(\s*['"]([^'"]+)['"]"#).unwrap(), "express"),
        (Regex::new(r#"path\s*==\s*['"]([^'"]+)['"]"#).unwrap(), "xray_custom"),
    ];

    let method_from_ctx = Regex::new(r#"\.(?:get|post|put|delete|patch)\("#).unwrap();
    let method_hint = Regex::new(r#"(?i)(?:method|methods)\s*[:=]\s*['"\[]*\s*(GET|POST|PUT|DELETE|PATCH)"#).unwrap();
    let input_re = Regex::new(
        r"(?:request\.(?:json|form|args|data|files|values|get_json|POST|GET|body|query_params)|req\.(?:body|params|query|file|files)|self\._read_body\(\))"
    ).unwrap();

    let mut ui_actions: Vec<serde_json::Value> = Vec::new();
    let mut handlers: Vec<serde_json::Value> = Vec::new();
    let mut frameworks: BTreeSet<String> = BTreeSet::new();

    // Phase A: Parse frontend files
    for (fpath, rel) in walk_ext(directory, FRONTEND_EXTS) {
        let content = match std::fs::read_to_string(&fpath) {
            Ok(c) => c,
            Err(_) => continue,
        };
        let rel_fwd = fwd(&rel);
        for (pat, call_type) in &fe_patterns {
            for m in pat.find_iter(&content) {
                if let Some(caps) = pat.captures(&content[m.start()..]) {
                    let url = caps.get(1).map_or("", |m| m.as_str()).to_string();
                    if !is_relative_api(&url) {
                        continue;
                    }
                    let line = content[..m.start()].matches('\n').count() + 1;
                    let ctx_start = floor_char_boundary(&content, m.start().saturating_sub(100));
                    let ctx_end = ceil_char_boundary(&content, (m.end() + 100).min(content.len()));
                    let ctx = &content[ctx_start..ctx_end];
                    let method = infer_method(ctx, call_type);
                    let url_clean = url.split('?').next().unwrap_or(&url).to_string();
                    ui_actions.push(serde_json::json!({
                        "file": rel_fwd,
                        "line": line,
                        "call_type": call_type,
                        "url": url_clean,
                        "method": method,
                    }));
                }
            }
        }
    }

    // Phase B: Parse backend files
    for (fpath, rel) in walk_ext(directory, BACKEND_EXTS) {
        let content = match std::fs::read_to_string(&fpath) {
            Ok(c) => c,
            Err(_) => continue,
        };
        let rel_fwd = fwd(&rel);
        let lines_vec: Vec<&str> = content.lines().collect();
        for (pat, framework) in &be_patterns {
            for m in pat.find_iter(&content) {
                if let Some(caps) = pat.captures(&content[m.start()..]) {
                    let mut route = caps.get(1).map_or("", |m| m.as_str()).to_string();
                    if !route.starts_with('/') {
                        route = format!("/{}", route);
                    }
                    let line = content[..m.start()].matches('\n').count() + 1;
                    frameworks.insert(framework.to_string());

                    let ctx_start = floor_char_boundary(&content, m.start().saturating_sub(60));
                    let ctx_end = ceil_char_boundary(&content, (m.end() + 60).min(content.len()));
                    let ctx = &content[ctx_start..ctx_end];

                    let method = if let Some(mc) = method_from_ctx.find(ctx) {
                        let s = mc.as_str();
                        s[1..s.len()-1].to_uppercase()
                    } else if let Some(mc) = method_hint.captures(ctx) {
                        mc[1].to_uppercase()
                    } else {
                        "ANY".into()
                    };

                    let body_end = (line + 30).min(lines_vec.len());
                    let body_text: String = lines_vec[line.saturating_sub(1)..body_end].join("\n");
                    let receives_input = input_re.is_match(&body_text);

                    handlers.push(serde_json::json!({
                        "file": rel_fwd,
                        "line": line,
                        "route": route,
                        "method": method,
                        "framework": framework,
                        "receives_input": receives_input,
                    }));
                }
            }
        }
    }

    // Phase C: Wire connections
    let mut ui_by_path: HashMap<String, Vec<&serde_json::Value>> = HashMap::new();
    for a in &ui_actions {
        let url = a["url"].as_str().unwrap_or("");
        ui_by_path.entry(normalize_route(url)).or_default().push(a);
    }
    let mut be_by_path: HashMap<String, Vec<&serde_json::Value>> = HashMap::new();
    for h in &handlers {
        let route = h["route"].as_str().unwrap_or("");
        be_by_path.entry(normalize_route(route)).or_default().push(h);
    }

    let mut all_paths: BTreeSet<String> = BTreeSet::new();
    all_paths.extend(ui_by_path.keys().cloned());
    all_paths.extend(be_by_path.keys().cloned());

    let mut wired: Vec<serde_json::Value> = Vec::new();
    let mut orphan_ui: Vec<serde_json::Value> = Vec::new();
    let mut orphan_backend: Vec<serde_json::Value> = Vec::new();
    let mut card_counts = serde_json::json!({"1:1": 0, "1:many": 0, "many:1": 0});

    for path in &all_paths {
        let ui_list = ui_by_path.get(path).cloned().unwrap_or_default();
        let be_list = be_by_path.get(path).cloned().unwrap_or_default();

        if !ui_list.is_empty() && !be_list.is_empty() {
            let cardinality = if ui_list.len() == 1 && be_list.len() == 1 {
                "1:1"
            } else if ui_list.len() > 1 {
                "many:1"
            } else {
                "1:many"
            };
            *card_counts.get_mut(cardinality).unwrap() = serde_json::json!(
                card_counts[cardinality].as_u64().unwrap_or(0) + 1
            );
            let ui_capped: Vec<&serde_json::Value> = ui_list.iter().take(20).cloned().collect();
            let be_capped: Vec<&serde_json::Value> = be_list.iter().take(20).cloned().collect();
            wired.push(serde_json::json!({
                "url": ui_list[0]["url"],
                "cardinality": cardinality,
                "ui_actions": ui_capped,
                "handlers": be_capped,
            }));
        } else if !ui_list.is_empty() {
            for a in ui_list.iter().take(20) {
                orphan_ui.push((*a).clone());
            }
        } else if !be_list.is_empty() {
            for h in be_list.iter().take(20) {
                orphan_backend.push((*h).clone());
            }
        }
    }

    wired.truncate(500);
    orphan_ui.truncate(500);
    orphan_backend.truncate(500);

    serde_json::json!({
        "wired": wired,
        "orphan_ui": orphan_ui,
        "orphan_backend": orphan_backend,
        "summary": {
            "total_ui_actions": ui_actions.len(),
            "total_handlers": handlers.len(),
            "wired_count": wired.len(),
            "orphan_ui_count": orphan_ui.len(),
            "orphan_backend_count": orphan_backend.len(),
            "cardinality": card_counts,
        },
        "frameworks_detected": frameworks.into_iter().collect::<Vec<_>>(),
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

    // ── normalize_route ─────────────────────────────────────────────

    #[test]
    fn test_normalize_route_strips_trailing_slash() {
        assert_eq!(normalize_route("/api/items/"), "/api/items");
    }

    #[test]
    fn test_normalize_route_replaces_flask_params() {
        assert_eq!(normalize_route("/api/items/<int:id>"), "/api/items/_PARAM_");
    }

    #[test]
    fn test_normalize_route_replaces_express_params() {
        assert_eq!(normalize_route("/api/items/:id"), "/api/items/_PARAM_");
    }

    #[test]
    fn test_normalize_route_replaces_braces_params() {
        assert_eq!(normalize_route("/api/items/{item_id}"), "/api/items/_PARAM_");
    }

    #[test]
    fn test_normalize_route_strips_query_string() {
        assert_eq!(normalize_route("/api/items?sort=asc"), "/api/items");
    }

    #[test]
    fn test_normalize_route_root() {
        assert_eq!(normalize_route("/"), "/");
    }

    // ── char boundary helpers ───────────────────────────────────────

    #[test]
    fn test_floor_char_boundary_ascii() {
        let s = "hello";
        assert_eq!(floor_char_boundary(s, 3), 3);
    }

    #[test]
    fn test_floor_char_boundary_multibyte() {
        let s = "héllo"; // é is 2 bytes in UTF-8
        // Index 2 is the second byte of é, should snap back to 1
        assert!(floor_char_boundary(s, 2) <= 2);
        assert!(s.is_char_boundary(floor_char_boundary(s, 2)));
    }

    #[test]
    fn test_ceil_char_boundary_ascii() {
        let s = "hello";
        assert_eq!(ceil_char_boundary(s, 3), 3);
    }

    #[test]
    fn test_ceil_char_boundary_past_end() {
        let s = "hello";
        assert_eq!(ceil_char_boundary(s, 100), s.len());
    }

    #[test]
    fn test_floor_char_boundary_past_end() {
        let s = "hello";
        assert_eq!(floor_char_boundary(s, 100), s.len());
    }

    // ── is_relative_api ─────────────────────────────────────────────

    #[test]
    fn test_relative_api_yes() {
        assert!(is_relative_api("/api/scan"));
        assert!(is_relative_api("/items"));
    }

    #[test]
    fn test_relative_api_no() {
        assert!(!is_relative_api("https://example.com/api"));
        assert!(!is_relative_api("http://localhost/api"));
        assert!(!is_relative_api("//cdn.example.com/api"));
        assert!(!is_relative_api("data.json"));
    }

    // ── infer_method ────────────────────────────────────────────────

    #[test]
    fn test_infer_method_form_action() {
        assert_eq!(infer_method("", "form_action"), "POST");
    }

    #[test]
    fn test_infer_method_explicit() {
        assert_eq!(infer_method("method: 'DELETE'", "fetch"), "DELETE");
    }

    #[test]
    fn test_infer_method_unknown() {
        assert_eq!(infer_method("some unrelated context", "fetch"), "UNKNOWN");
    }

    // ── analyze_connections (integration) ───────────────────────────

    #[test]
    fn test_connections_shape_empty() {
        let (_dir, path) = make_temp_project(&[("readme.txt", "no code here")]);
        let result = analyze_connections(&path);
        assert!(result.get("wired").is_some());
        assert!(result.get("orphan_ui").is_some());
        assert!(result.get("orphan_backend").is_some());
        assert!(result.get("summary").is_some());
        assert!(result.get("frameworks_detected").is_some());
        let summary = &result["summary"];
        assert_eq!(summary["total_ui_actions"].as_u64().unwrap(), 0);
        assert_eq!(summary["total_handlers"].as_u64().unwrap(), 0);
    }

    #[test]
    fn test_connections_detects_flask_backend() {
        let code = r#"
from flask import Flask
app = Flask(__name__)

@app.route('/api/items')
def get_items():
    return []
"#;
        let (_dir, path) = make_temp_project(&[("server.py", code)]);
        let result = analyze_connections(&path);
        let summary = &result["summary"];
        assert!(summary["total_handlers"].as_u64().unwrap() >= 1,
            "Should detect flask route handler");
        let fw = result["frameworks_detected"].as_array().unwrap();
        let fw_strs: Vec<&str> = fw.iter().filter_map(|v| v.as_str()).collect();
        assert!(fw_strs.contains(&"flask"), "Should detect flask framework");
    }

    #[test]
    fn test_connections_detects_fetch_frontend() {
        let code = r#"
async function loadItems() {
    const resp = await fetch('/api/items');
    return resp.json();
}
"#;
        let (_dir, path) = make_temp_project(&[("app.js", code)]);
        let result = analyze_connections(&path);
        let summary = &result["summary"];
        assert!(summary["total_ui_actions"].as_u64().unwrap() >= 1,
            "Should detect fetch UI action");
    }

    #[test]
    fn test_connections_wires_matching_routes() {
        let frontend = r#"
async function loadItems() {
    const resp = await fetch('/api/items');
    return resp.json();
}
"#;
        let backend = r#"
from flask import Flask
app = Flask(__name__)

@app.route('/api/items')
def get_items():
    return []
"#;
        let (_dir, path) = make_temp_project(&[("app.js", frontend), ("server.py", backend)]);
        let result = analyze_connections(&path);
        let wired = result["wired"].as_array().unwrap();
        assert!(!wired.is_empty(), "Should wire matching frontend/backend routes");
        let first = &wired[0];
        assert!(first.get("ui_actions").is_some());
        assert!(first.get("handlers").is_some());
        assert!(first.get("cardinality").is_some());
    }

    #[test]
    fn test_connections_orphan_backend() {
        let code = r#"
from flask import Flask
app = Flask(__name__)

@app.route('/api/secret')
def secret():
    return 'hidden'
"#;
        let (_dir, path) = make_temp_project(&[("server.py", code)]);
        let result = analyze_connections(&path);
        let orphans = result["orphan_backend"].as_array().unwrap();
        assert!(!orphans.is_empty(), "Backend route with no frontend should be orphaned");
    }

    #[test]
    fn test_connections_orphan_ui() {
        let code = r#"
async function loadStuff() {
    const resp = await fetch('/api/nowhere');
    return resp.json();
}
"#;
        let (_dir, path) = make_temp_project(&[("app.js", code)]);
        let result = analyze_connections(&path);
        let orphans = result["orphan_ui"].as_array().unwrap();
        assert!(!orphans.is_empty(), "Frontend fetch with no backend should be orphaned");
    }
}
