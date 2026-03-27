//! API route handlers — port of api/*.py.

use axum::{
    extract::{Query, State as AxumState},
    http::StatusCode,
    response::{IntoResponse, Json},
};
use serde::Deserialize;
use std::collections::HashMap;
use std::path::Path;
use std::sync::Arc;

use super::state::AppState;
use crate::analyzers;
use crate::fixer;
use crate::rules::get_all_rules;
use crate::sarif;

// ── Helpers ──────────────────────────────────────────────────────────────────

#[derive(Deserialize, Default)]
pub struct DirBody {
    #[serde(default)]
    pub directory: String,
    #[serde(default)]
    pub engine: String,
    #[serde(default)]
    pub severity: String,
    #[serde(default)]
    pub excludes: Vec<String>,
    #[serde(default)]
    pub findings: Vec<serde_json::Value>,
    #[serde(default)]
    pub smells: Vec<serde_json::Value>,
    #[serde(default)]
    pub dead_functions: Vec<serde_json::Value>,
    #[serde(default)]
    pub file: String,
    #[serde(default)]
    pub line: usize,
    #[serde(default)]
    pub rule_id: String,
    #[serde(default)]
    pub days: Option<u32>,
    #[serde(default)]
    pub files_scanned: usize,
    #[serde(default)]
    pub summary: Option<serde_json::Value>,
    #[serde(default)]
    pub health: Option<serde_json::Value>,
    #[serde(default)]
    pub satd: Option<serde_json::Value>,
    #[serde(default)]
    pub duplicates: Option<serde_json::Value>,
}

fn validate_dir(directory: &str) -> Result<String, (StatusCode, Json<serde_json::Value>)> {
    if directory.is_empty() || !Path::new(directory).is_dir() {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"error": format!("Invalid directory: {}", directory)})),
        ));
    }
    let resolved = std::fs::canonicalize(directory)
        .unwrap_or_else(|_| Path::new(directory).to_path_buf());
    Ok(clean_path(&resolved.to_string_lossy()))
}

// ── GET routes ───────────────────────────────────────────────────────────────

pub async fn info() -> impl IntoResponse {
    let rules = get_all_rules();
    let fixable: Vec<&str> = vec!["SEC-003", "SEC-009", "QUAL-001", "QUAL-003", "QUAL-004", "PY-005", "PY-007"];
    let home = dirs_home().unwrap_or_default();
    Json(serde_json::json!({
        "platform": format!("{} {}", std::env::consts::OS, std::env::consts::ARCH),
        "python": null,
        "engine": "rust",
        "rust_available": true,
        "rust_binary": std::env::current_exe().ok().map(|p| clean_path(&p.to_string_lossy())),
        "rules_count": rules.len(),
        "fixable_rules": fixable,
        "home": home,
    }))
}

fn dirs_home() -> Option<String> {
    #[cfg(windows)]
    {
        std::env::var("USERPROFILE").ok().map(|p| p.replace('\\', "/"))
    }
    #[cfg(not(windows))]
    {
        std::env::var("HOME").ok()
    }
}

/// Strip Windows \\?\ extended-path prefix and normalise backslashes to /
fn clean_path(p: &str) -> String {
    let s = p.replace('\\', "/");
    if s.starts_with("//?/") { s[4..].to_string() } else { s }
}

pub async fn browse(Query(params): Query<HashMap<String, String>>) -> impl IntoResponse {
    let dir_path = params.get("path").cloned().unwrap_or_default();
    if dir_path.is_empty() {
        // Return drives / root
        #[cfg(windows)]
        {
            let drives: Vec<serde_json::Value> = (b'C'..=b'Z')
                .filter_map(|d| {
                    let p = format!("{}:/", d as char);
                    if Path::new(&format!("{}:\\", d as char)).exists() {
                        Some(serde_json::json!({"name": format!("{}:", d as char), "path": p, "is_dir": true}))
                    } else { None }
                })
                .collect();
            return Json(serde_json::json!({"drives": drives}));
        }
        #[cfg(not(windows))]
        {
            return Json(serde_json::json!({"drives": [{"name": "/", "path": "/", "is_dir": true}]}));
        }
    }
    let path = Path::new(&dir_path);
    if !path.is_dir() {
        return Json(serde_json::json!({"error": "Not a directory"}));
    }
    let resolved = std::fs::canonicalize(path).unwrap_or_else(|_| path.to_path_buf());
    let mut items: Vec<serde_json::Value> = Vec::new();
    if let Ok(entries) = std::fs::read_dir(&resolved) {
        for entry in entries.filter_map(|e| e.ok()) {
            let name = entry.file_name().to_string_lossy().into_owned();
            // Skip hidden files/dirs (starting with .)
            if name.starts_with('.') { continue; }
            let is_dir = entry.file_type().map(|t| t.is_dir()).unwrap_or(false);
            let size = if !is_dir {
                entry.metadata().map(|m| m.len()).ok()
            } else { None };
            items.push(serde_json::json!({
                "name": name,
                "is_dir": is_dir,
                "path": clean_path(&entry.path().to_string_lossy()),
                "size": size,
            }));
        }
    }
    items.sort_by(|a, b| {
        let ad = a["is_dir"].as_bool().unwrap_or(false);
        let bd = b["is_dir"].as_bool().unwrap_or(false);
        bd.cmp(&ad).then(
            a["name"].as_str().unwrap_or("").to_lowercase().cmp(
                &b["name"].as_str().unwrap_or("").to_lowercase()
            )
        )
    });
    // Compute parent path
    let parent = resolved.parent().map(|p| clean_path(&p.to_string_lossy()));
    let current = clean_path(&resolved.to_string_lossy());
    Json(serde_json::json!({"items": items, "current": current, "parent": parent}))
}

pub async fn scan_result(AxumState(state): AxumState<Arc<AppState>>) -> impl IntoResponse {
    let guard = state.last_scan_result.lock().unwrap();
    if let Some(ref result) = *guard {
        // Build severity counts for summary — Python uses lowercase keys
        let mut high = 0u32;
        let mut medium = 0u32;
        let mut low = 0u32;
        let findings: Vec<serde_json::Value> = result.findings.iter().map(|f| {
            match f.severity.as_str() {
                "HIGH" => high += 1,
                "MEDIUM" => medium += 1,
                _ => low += 1,
            }
            serde_json::json!({
                "rule_id": f.rule_id,
                "severity": f.severity,
                "file": clean_path(&f.file),
                "line": f.line,
                "col": 0,
                "matched_text": "",
                "description": f.description,
                "fix_hint": f.fix_hint,
                "test_hint": "",
            })
        }).collect();
        let total = high + medium + low;
        // Read elapsed_ms from progress if available
        let elapsed = state.scan_elapsed_ms.lock().unwrap();
        Json(serde_json::json!({
            "engine": "rust",
            "elapsed_ms": *elapsed,
            "files_scanned": result.files_scanned,
            "findings": findings,
            "errors": [],
            "summary": {"total": total, "high": high, "medium": medium, "low": low},
        }))
    } else {
        Json(serde_json::json!({"error": "No scan results available"}))
    }
}

pub async fn scan_progress(AxumState(state): AxumState<Arc<AppState>>) -> impl IntoResponse {
    let guard = state.scan_progress.lock().unwrap();
    if let Some(ref p) = *guard {
        Json(p.clone())
    } else {
        Json(serde_json::json!({
            "status": "idle",
            "files_scanned": 0,
            "total_files": 0,
            "findings_count": 0,
            "elapsed_ms": 0.0,
        }))
    }
}

// ── POST routes – scanning ───────────────────────────────────────────────────

pub async fn scan(
    AxumState(state): AxumState<Arc<AppState>>,
    Json(body): Json<DirBody>,
) -> impl IntoResponse {
    let directory = match validate_dir(&body.directory) {
        Ok(d) => d,
        Err(e) => return e.into_response(),
    };
    state.reset_scan();

    // Run scan in blocking task
    let state_clone = Arc::clone(&state);
    let excludes = body.excludes.clone();
    let severity = if body.severity.is_empty() { "LOW".to_string() } else { body.severity.clone() };

    tokio::task::spawn_blocking(move || {
        let scan_start = std::time::Instant::now();
        // Mark progress as "scanning" immediately so the UI knows we're running
        *state_clone.scan_progress.lock().unwrap() = Some(serde_json::json!({
            "status": "scanning",
            "files_scanned": 0,
            "total_files": 0,
            "findings_count": 0,
        }));

        let scan_result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let rules = get_all_rules();
            let result = crate::scan_directory_with_excludes(
                std::path::Path::new(&directory),
                &rules,
                &excludes.iter().map(|s| s.as_str()).collect::<Vec<_>>(),
            );
            // Filter by severity
            let severity_levels: Vec<&str> = match severity.as_str() {
                "HIGH" => vec!["HIGH"],
                "MEDIUM" => vec!["HIGH", "MEDIUM"],
                _ => vec!["HIGH", "MEDIUM", "LOW"],
            };
            let filtered_findings: Vec<_> = result
                .findings
                .into_iter()
                .filter(|f| severity_levels.contains(&f.severity.as_str()))
                .collect();

            crate::ScanResult {
                findings: filtered_findings,
                ..result
            }
        }));

        match scan_result {
            Ok(final_result) => {
                let elapsed_ms = scan_start.elapsed().as_secs_f64() * 1000.0;
                let elapsed_ms = (elapsed_ms * 10.0).round() / 10.0; // 1 decimal place
                *state_clone.scan_elapsed_ms.lock().unwrap() = elapsed_ms;
                *state_clone.scan_progress.lock().unwrap() = Some(serde_json::json!({
                    "status": "done",
                    "files_scanned": final_result.files_scanned,
                    "total_files": final_result.files_scanned,
                    "findings_count": final_result.findings.len(),
                    "elapsed_ms": elapsed_ms,
                }));
                *state_clone.last_scan_result.lock().unwrap() = Some(final_result);
            }
            Err(panic_info) => {
                let msg = if let Some(s) = panic_info.downcast_ref::<&str>() {
                    s.to_string()
                } else if let Some(s) = panic_info.downcast_ref::<String>() {
                    s.clone()
                } else {
                    "Unknown panic".to_string()
                };
                eprintln!("[xray] SCAN PANIC: {}", msg);
                *state_clone.scan_progress.lock().unwrap() = Some(serde_json::json!({
                    "status": "done",
                    "files_scanned": 0,
                    "total_files": 0,
                    "findings_count": 0,
                    "error": format!("Scan panicked: {}", msg),
                }));
            }
        }
    });

    (StatusCode::OK, Json(serde_json::json!({"status": "started"}))).into_response()
}

pub async fn abort(AxumState(state): AxumState<Arc<AppState>>) -> impl IntoResponse {
    state.abort.store(true, std::sync::atomic::Ordering::Relaxed);
    Json(serde_json::json!({"ok": true}))
}

// ── POST routes – fixers ─────────────────────────────────────────────────────

pub async fn preview_fix(Json(body): Json<DirBody>) -> impl IntoResponse {
    let finding = serde_json::json!({
        "file": body.file,
        "line": body.line,
        "rule_id": body.rule_id,
    });
    let result = fixer::preview_fix(&finding);
    Json(serde_json::to_value(result).unwrap_or_default())
}

pub async fn apply_fix(Json(body): Json<DirBody>) -> impl IntoResponse {
    let finding = serde_json::json!({
        "file": body.file,
        "line": body.line,
        "rule_id": body.rule_id,
    });
    let result = fixer::apply_fix(&finding);
    Json(serde_json::to_value(result).unwrap_or_default())
}

// ── POST routes – analyzers ──────────────────────────────────────────────────

pub async fn health(Json(body): Json<DirBody>) -> impl IntoResponse {
    let dir = match validate_dir(&body.directory) {
        Ok(d) => d,
        Err(e) => return e.into_response(),
    };
    let result = analyzers::health::check_project_health(&dir);
    Json(result).into_response()
}

pub async fn smells(Json(body): Json<DirBody>) -> impl IntoResponse {
    let dir = match validate_dir(&body.directory) {
        Ok(d) => d,
        Err(e) => return e.into_response(),
    };
    let result = analyzers::smells::detect_code_smells(&dir);
    Json(result).into_response()
}

pub async fn dead_code(Json(body): Json<DirBody>) -> impl IntoResponse {
    let dir = match validate_dir(&body.directory) {
        Ok(d) => d,
        Err(e) => return e.into_response(),
    };
    let result = analyzers::smells::detect_dead_functions(&dir);
    Json(result).into_response()
}

pub async fn duplicates(Json(body): Json<DirBody>) -> impl IntoResponse {
    let dir = match validate_dir(&body.directory) {
        Ok(d) => d,
        Err(e) => return e.into_response(),
    };
    let result = analyzers::smells::detect_duplicates(&dir);
    Json(result).into_response()
}

pub async fn format_check(Json(body): Json<DirBody>) -> impl IntoResponse {
    let dir = match validate_dir(&body.directory) {
        Ok(d) => d,
        Err(e) => return e.into_response(),
    };
    let result = analyzers::format_check::check_format(&dir);
    Json(result).into_response()
}

pub async fn type_check(Json(body): Json<DirBody>) -> impl IntoResponse {
    let dir = match validate_dir(&body.directory) {
        Ok(d) => d,
        Err(e) => return e.into_response(),
    };
    let result = analyzers::format_check::check_types(&dir);
    Json(result).into_response()
}

pub async fn connection_test(Json(body): Json<DirBody>) -> impl IntoResponse {
    let dir = match validate_dir(&body.directory) {
        Ok(d) => d,
        Err(e) => return e.into_response(),
    };
    let result = analyzers::connections::analyze_connections(&dir);
    Json(result).into_response()
}

pub async fn release_readiness(Json(body): Json<DirBody>) -> impl IntoResponse {
    let dir = match validate_dir(&body.directory) {
        Ok(d) => d,
        Err(e) => return e.into_response(),
    };
    let result = analyzers::health::check_release_readiness(&dir);
    Json(result).into_response()
}

pub async fn remediation_time(Json(body): Json<DirBody>) -> impl IntoResponse {
    let result = analyzers::health::estimate_remediation_time(&body.findings);
    Json(result).into_response()
}

// ── POST routes – graph / PM dashboard ───────────────────────────────────────

pub async fn circular_calls(Json(body): Json<DirBody>) -> impl IntoResponse {
    let dir = match validate_dir(&body.directory) {
        Ok(d) => d,
        Err(e) => return e.into_response(),
    };
    let result = analyzers::graph::detect_circular_calls(&dir);
    Json(result).into_response()
}

pub async fn coupling(Json(body): Json<DirBody>) -> impl IntoResponse {
    let dir = match validate_dir(&body.directory) {
        Ok(d) => d,
        Err(e) => return e.into_response(),
    };
    let result = analyzers::graph::compute_coupling_metrics(&dir);
    Json(result).into_response()
}

pub async fn unused_imports(Json(body): Json<DirBody>) -> impl IntoResponse {
    let dir = match validate_dir(&body.directory) {
        Ok(d) => d,
        Err(e) => return e.into_response(),
    };
    let result = analyzers::graph::detect_unused_imports(&dir);
    Json(result).into_response()
}

// ── SARIF ────────────────────────────────────────────────────────────────────

pub async fn sarif_export(
    AxumState(state): AxumState<Arc<AppState>>,
    Json(body): Json<DirBody>,
) -> impl IntoResponse {
    let guard = state.last_scan_result.lock().unwrap();
    if let Some(ref result) = *guard {
        let findings_json: Vec<serde_json::Value> = result.findings.iter().map(|f| serde_json::json!({
            "rule_id": f.rule_id,
            "severity": f.severity,
            "file": f.file,
            "line": f.line,
            "description": f.description,
            "fix_hint": f.fix_hint,
        })).collect();
        let path = if body.file.is_empty() {
            "xray_scan.sarif".to_string()
        } else {
            body.file.clone()
        };
        if let Err(e) = sarif::write_sarif(&findings_json, &path) {
            return Json(serde_json::json!({"error": format!("Failed to write SARIF: {}", e)})).into_response();
        }
        Json(serde_json::json!({"ok": true, "path": path})).into_response()
    } else {
        (StatusCode::NOT_FOUND, Json(serde_json::json!({"error": "No scan results to export"}))).into_response()
    }
}
