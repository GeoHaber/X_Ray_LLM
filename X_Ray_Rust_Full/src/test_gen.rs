// src/test_gen.rs — Test input generation and ground-truth capture
//
// Port of Analysis/test_gen.py
// Parses Python function signatures and generates diverse test inputs.
// Also provides a reference generator for capturing I/O fixtures.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::Path;

use crate::types::FunctionRecord;

/// A single test case: mapping of parameter names to input values.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TestCase {
    pub inputs: HashMap<String, serde_json::Value>,
}

/// Result of capturing ground-truth execution.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CapturedResult {
    pub input: serde_json::Value,
    pub output: Option<serde_json::Value>,
    pub status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

/// A complete fixture file payload.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FixturePayload {
    pub function: String,
    pub signature: String,
    pub cases: Vec<CapturedResult>,
}

// ── String-like parameter names ──────────────────────────────────────────

const STRING_PARAM_NAMES: &[&str] = &["text", "code", "name", "s", "source", "content", "msg", "path", "filename", "line", "pattern"];

fn is_string_param(name: &str) -> bool {
    STRING_PARAM_NAMES.contains(&name)
}

// ── Input generation ─────────────────────────────────────────────────────

/// Generate diverse test inputs for a function based on its parameters.
pub fn generate_inputs(func: &FunctionRecord) -> Vec<TestCase> {
    let params: Vec<&str> = func
        .parameters
        .iter()
        .map(|s| s.as_str())
        .filter(|p| *p != "self" && *p != "cls")
        .collect();

    if params.is_empty() {
        // No-arg function: one empty test case
        return vec![TestCase {
            inputs: HashMap::new(),
        }];
    }

    let str_params: Vec<&str> = params.iter().copied().filter(|p| is_string_param(p)).collect();
    let num_params: Vec<&str> = params
        .iter()
        .copied()
        .filter(|p| !is_string_param(p))
        .collect();

    if !str_params.is_empty() {
        generate_string_cases(&str_params, &num_params)
    } else {
        generate_numeric_cases(&params)
    }
}

/// Generate test cases for string-like arguments.
fn generate_string_cases(str_params: &[&str], num_params: &[&str]) -> Vec<TestCase> {
    let string_values = [
        "basic_test",
        "",
        "CamelCase",
        "hello world",
        "a" ,
        "def foo():\n    pass",
    ];
    let num_values: &[i64] = &[10, 0, 1, -1, 100, 42];

    string_values
        .iter()
        .zip(num_values.iter().cycle())
        .map(|(sv, nv)| {
            let mut inputs = HashMap::new();
            for &sp in str_params {
                inputs.insert(sp.to_string(), serde_json::Value::String(sv.to_string()));
            }
            for &np in num_params {
                inputs.insert(np.to_string(), serde_json::json!(*nv));
            }
            TestCase { inputs }
        })
        .collect()
}

/// Generate test cases for numeric arguments.
fn generate_numeric_cases(params: &[&str]) -> Vec<TestCase> {
    let value_sets: &[&[i64]] = &[
        &[0],
        &[1],
        &[-1],
        &[42],
        &[100],
        &[999],
    ];

    value_sets
        .iter()
        .map(|vals| {
            let mut inputs = HashMap::new();
            for (i, &p) in params.iter().enumerate() {
                let v = vals[i % vals.len()];
                inputs.insert(p.to_string(), serde_json::json!(v));
            }
            TestCase { inputs }
        })
        .collect()
}

/// Generate a signature string from a FunctionRecord.
pub fn format_signature(func: &FunctionRecord) -> String {
    let params = func
        .parameters
        .iter()
        .filter(|p| *p != "self" && *p != "cls")
        .cloned()
        .collect::<Vec<_>>()
        .join(", ");

    let ret = func
        .return_type
        .as_ref()
        .map(|r| format!(" -> {}", r))
        .unwrap_or_default();

    format!("{}({}){}", func.name, params, ret)
}

/// Save a fixture file for a function's captured test results.
pub fn save_fixture(
    func: &FunctionRecord,
    cases: &[CapturedResult],
    output_dir: &Path,
) -> std::io::Result<String> {
    std::fs::create_dir_all(output_dir)?;

    let payload = FixturePayload {
        function: func.name.clone(),
        signature: format_signature(func),
        cases: cases.to_vec(),
    };

    let filename = format!("{}_verification.json", func.name);
    let path = output_dir.join(&filename);
    let json = serde_json::to_string_pretty(&payload).unwrap_or_else(|_| "{}".to_string());
    std::fs::write(&path, json)?;

    Ok(path.to_string_lossy().to_string())
}

/// Generate test cases for multiple functions at once.
pub fn batch_generate(functions: &[FunctionRecord]) -> Vec<(String, Vec<TestCase>)> {
    functions
        .iter()
        .map(|f| (f.key(), generate_inputs(f)))
        .collect()
}
