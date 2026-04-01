//! PyO3 bridge -- exposes the Rust scanner to Python as a native extension.
//!
//! Usage from Python:
//!   import xray_native
//!   result = xray_native.scan_file("/path/to/file.py")
//!   result = xray_native.scan_directory("/path/to/project")

use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::path::Path;

use crate::rules::get_all_rules;
use crate::fixer::{preview_fix, apply_fix, FIXABLE_RULES};

/// Convert a single Finding into a Python dict.
fn finding_to_pydict(py: Python<'_>, f: &crate::Finding) -> PyResult<PyObject> {
    let dict = PyDict::new(py);
    dict.set_item("rule_id", &f.rule_id)?;
    dict.set_item("severity", &f.severity)?;
    dict.set_item("file", &f.file)?;
    dict.set_item("line", f.line)?;
    dict.set_item("col", f.col)?;
    dict.set_item("matched_text", &f.matched_text)?;
    dict.set_item("description", &f.description)?;
    dict.set_item("fix_hint", &f.fix_hint)?;
    dict.set_item("test_hint", &f.test_hint)?;
    dict.set_item("cwe", &f.cwe)?;
    dict.set_item("owasp", &f.owasp)?;
    dict.set_item("confidence", f.confidence)?;
    dict.set_item("signal_path", &f.signal_path)?;
    dict.set_item("why_flagged", &f.why_flagged)?;
    Ok(dict.into())
}

/// Convert a FixResult into a Python dict.
fn fix_result_to_pydict(py: Python<'_>, r: &crate::fixer::FixResult) -> PyResult<PyObject> {
    let dict = PyDict::new(py);
    dict.set_item("fixable", r.fixable)?;
    dict.set_item("description", &r.description)?;
    dict.set_item("diff", &r.diff)?;
    dict.set_item("error", &r.error)?;
    Ok(dict.into())
}

/// Build a serde_json::Value finding for the fixer API from filepath, rule_id, line.
fn make_finding_value(filepath: &str, rule_id: &str, line: usize) -> serde_json::Value {
    serde_json::json!({
        "file": filepath,
        "rule_id": rule_id,
        "line": line,
        "matched_text": "",
        "fix_hint": "",
    })
}

// ---- Exported Python functions ------------------------------------------------

/// Scan a single file and return findings as a list of dicts.
#[pyfunction]
fn py_scan_file(path: &str) -> PyResult<Vec<PyObject>> {
    let rules = get_all_rules();
    let findings = crate::scan_file(Path::new(path), &rules);
    Python::with_gil(|py| {
        findings
            .iter()
            .map(|f| finding_to_pydict(py, f))
            .collect()
    })
}

/// Scan a directory and return a full result dict.
#[pyfunction]
#[pyo3(signature = (root, exclude_patterns=None, incremental=None))]
fn py_scan_directory(
    root: &str,
    exclude_patterns: Option<Vec<String>>,
    incremental: Option<bool>,
) -> PyResult<PyObject> {
    let rules = get_all_rules();
    let excludes = exclude_patterns.unwrap_or_default();
    let inc = incremental.unwrap_or(false);

    let result = crate::scan_directory_with_options(
        Path::new(root),
        &rules,
        &excludes,
        inc,
        None,
    );

    Python::with_gil(|py| {
        let dict = PyDict::new(py);

        let py_findings: Vec<PyObject> = result
            .findings
            .iter()
            .map(|f| finding_to_pydict(py, f))
            .collect::<PyResult<Vec<_>>>()?;

        dict.set_item("findings", py_findings)?;
        dict.set_item("files_scanned", result.files_scanned)?;
        dict.set_item("rules_checked", result.rules_checked)?;
        dict.set_item("errors", &result.errors)?;
        dict.set_item("cached_files", result.cached_files)?;
        dict.set_item("grade", result.grade())?;
        Ok(dict.into())
    })
}

/// Preview a fix for a finding (returns a diff dict).
#[pyfunction]
fn py_preview_fix(filepath: &str, rule_id: &str, line: usize) -> PyResult<PyObject> {
    let finding = make_finding_value(filepath, rule_id, line);
    let result = preview_fix(&finding);
    Python::with_gil(|py| fix_result_to_pydict(py, &result))
}

/// Apply a fix to a file.
#[pyfunction]
fn py_apply_fix(filepath: &str, rule_id: &str, line: usize) -> PyResult<PyObject> {
    let finding = make_finding_value(filepath, rule_id, line);
    let result = apply_fix(&finding);
    Python::with_gil(|py| fix_result_to_pydict(py, &result))
}

/// Get list of fixable rule IDs.
#[pyfunction]
fn py_fixable_rules() -> Vec<String> {
    FIXABLE_RULES.iter().map(|s| s.to_string()).collect()
}

/// Get the version string.
#[pyfunction]
fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

/// Python module definition.
#[pymodule]
fn xray_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(py_scan_file, m)?)?;
    m.add_function(wrap_pyfunction!(py_scan_directory, m)?)?;
    m.add_function(wrap_pyfunction!(py_preview_fix, m)?)?;
    m.add_function(wrap_pyfunction!(py_apply_fix, m)?)?;
    m.add_function(wrap_pyfunction!(py_fixable_rules, m)?)?;
    m.add_function(wrap_pyfunction!(version, m)?)?;
    Ok(())
}
