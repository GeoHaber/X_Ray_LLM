//! X-Ray Fixer — Deterministic auto-fix for scanner findings.
//! Rust port of xray/fixer.py.
//!
//! Tier 1: Rule-based fixers (instant, no LLM) for known patterns.
//! Supports 7 rules: PY-005, PY-007, QUAL-001, QUAL-003, QUAL-004, SEC-003, SEC-009.

use regex::Regex;
use similar::TextDiff;
use std::path::Path;

/// Set of rule IDs that have auto-fixers.
pub const FIXABLE_RULES: &[&str] = &[
    "PY-005", "PY-007", "QUAL-001", "QUAL-003", "QUAL-004", "SEC-003", "SEC-009",
];

/// Result of an auto-fix attempt.
#[derive(Debug, Clone)]
#[derive(serde::Serialize)]
pub struct FixResult {
    pub fixable: bool,
    pub description: String,
    pub diff: String,
    pub new_lines: Option<Vec<String>>,
    pub error: String,
}

impl FixResult {
    fn err(msg: &str) -> Self {
        FixResult {
            fixable: false,
            description: String::new(),
            diff: String::new(),
            new_lines: None,
            error: msg.to_string(),
        }
    }

    fn success(description: &str, diff: String, new_lines: Vec<String>) -> Self {
        FixResult {
            fixable: true,
            description: description.to_string(),
            diff,
            new_lines: Some(new_lines),
            error: String::new(),
        }
    }

    pub fn to_json(&self) -> serde_json::Value {
        serde_json::json!({
            "fixable": self.fixable,
            "description": self.description,
            "diff": self.diff,
            "error": self.error,
        })
    }
}

fn read_file_lines(path: &str) -> Result<Vec<String>, String> {
    let content = std::fs::read_to_string(path)
        .map_err(|e| format!("Cannot read {path}: {e}"))?;
    Ok(content.lines().map(|l| format!("{l}\n")).collect())
}

fn make_diff(old_lines: &[String], new_lines: &[String], filepath: &str) -> String {
    let old_text: String = old_lines.concat();
    let new_text: String = new_lines.concat();
    let name = Path::new(filepath)
        .file_name()
        .unwrap_or_default()
        .to_string_lossy();
    let diff = TextDiff::from_lines(&old_text, &new_text);
    let mut output = String::new();
    output.push_str(&format!("--- a/{name}\n+++ b/{name}\n"));
    for hunk in diff.unified_diff().context_radius(3).iter_hunks() {
        output.push_str(&format!("{hunk}"));
    }
    output
}

fn get_indent(line: &str) -> &str {
    let trimmed = line.trim_start();
    &line[..line.len() - trimmed.len()]
}

fn in_try_block(lines: &[String], target_idx: usize) -> bool {
    let indent = get_indent(&lines[target_idx]);
    let start = target_idx.saturating_sub(20);
    for i in (start..target_idx).rev() {
        let stripped = lines[i].trim();
        if stripped == "try:" && get_indent(&lines[i]).len() < indent.len() {
            return true;
        }
        if !stripped.is_empty()
            && !stripped.starts_with('#')
            && get_indent(&lines[i]).len() <= indent.len()
            && !["try:", "if ", "elif ", "else:", "for ", "while "]
                .iter()
                .any(|p| stripped.starts_with(p))
        {
            break;
        }
    }
    false
}

// ── Individual fixers ──────────────────────────────────────────────────

/// PY-005: Wrap json.loads/json.load in try/except JSONDecodeError.
fn fix_py005(filepath: &str, line_num: usize, _matched: &str, lines: &[String]) -> FixResult {
    let idx = line_num - 1;
    if idx >= lines.len() {
        return FixResult::err("Line out of range");
    }
    if in_try_block(lines, idx) {
        return FixResult::err("Already in a try block");
    }

    let line = &lines[idx];
    let indent = get_indent(line);
    let inner = format!("{indent}    ");
    let code = line.trim_end();

    // Check for assignment
    let assign_re = Regex::new(r"^\s*(\w[\w.]*)\s*=\s*").unwrap();
    let default_var = assign_re.captures(line).map(|c| c[1].to_string());

    let mut new_block = Vec::new();
    new_block.push(format!("{indent}try:\n"));
    new_block.push(format!("{inner}{}\n", code.trim()));
    new_block.push(format!("{indent}except json.JSONDecodeError:\n"));
    if let Some(var) = default_var {
        new_block.push(format!("{inner}{var} = {{}}\n"));
    } else {
        new_block.push(format!("{inner}pass  # handle malformed JSON\n"));
    }

    let mut new_lines: Vec<String> = lines[..idx].to_vec();
    new_lines.extend(new_block);
    new_lines.extend_from_slice(&lines[idx + 1..]);
    let diff = make_diff(lines, &new_lines, filepath);
    FixResult::success("Wrapped json.loads() in try/except json.JSONDecodeError", diff, new_lines)
}

/// PY-007: Replace os.environ['KEY'] with os.environ.get('KEY', '').
fn fix_py007(filepath: &str, line_num: usize, _matched: &str, lines: &[String]) -> FixResult {
    let idx = line_num - 1;
    if idx >= lines.len() {
        return FixResult::err("Line out of range");
    }

    let line = &lines[idx];
    let re = Regex::new(r#"os\.environ\[(['"])(.+?)\1\]"#).unwrap();
    let new_line = re.replace_all(line, r#"os.environ.get($1$2$1, "")"#).to_string();
    if new_line == *line {
        return FixResult::err("Could not match pattern");
    }

    let mut new_lines: Vec<String> = lines[..idx].to_vec();
    new_lines.push(new_line);
    new_lines.extend_from_slice(&lines[idx + 1..]);
    let diff = make_diff(lines, &new_lines, filepath);
    FixResult::success("Replaced os.environ['KEY'] with os.environ.get('KEY', \"\")", diff, new_lines)
}

/// QUAL-001: Replace bare 'except:' with 'except Exception:'.
fn fix_qual001(filepath: &str, line_num: usize, _matched: &str, lines: &[String]) -> FixResult {
    let idx = line_num - 1;
    if idx >= lines.len() {
        return FixResult::err("Line out of range");
    }

    let line = &lines[idx];
    let re = Regex::new(r"except\s*:").unwrap();
    let new_line = re.replace(line, "except Exception:").to_string();
    if new_line == *line {
        return FixResult::err("Could not match bare except");
    }

    let mut new_lines: Vec<String> = lines[..idx].to_vec();
    new_lines.push(new_line);
    new_lines.extend_from_slice(&lines[idx + 1..]);
    let diff = make_diff(lines, &new_lines, filepath);
    FixResult::success("Replaced bare 'except:' with 'except Exception:'", diff, new_lines)
}

/// QUAL-003: Wrap unchecked int() on user input in try/except.
fn fix_qual003(filepath: &str, line_num: usize, _matched: &str, lines: &[String]) -> FixResult {
    fix_wrap_conversion(filepath, line_num, lines, "int()", "0")
}

/// QUAL-004: Wrap unchecked float() on user input in try/except.
fn fix_qual004(filepath: &str, line_num: usize, _matched: &str, lines: &[String]) -> FixResult {
    fix_wrap_conversion(filepath, line_num, lines, "float()", "0.0")
}

/// Shared logic for QUAL-003 and QUAL-004.
fn fix_wrap_conversion(
    filepath: &str,
    line_num: usize,
    lines: &[String],
    func_name: &str,
    default: &str,
) -> FixResult {
    let idx = line_num - 1;
    if idx >= lines.len() {
        return FixResult::err("Line out of range");
    }
    if in_try_block(lines, idx) {
        return FixResult::err("Already in a try block");
    }

    let line = &lines[idx];
    let indent = get_indent(line);
    let inner = format!("{indent}    ");
    let code = line.trim_end();

    let assign_re = Regex::new(r"^\s*(\w[\w.]*)\s*=\s*").unwrap();
    let default_var = assign_re.captures(line).map(|c| c[1].to_string());

    let mut new_block = Vec::new();
    new_block.push(format!("{indent}try:\n"));
    new_block.push(format!("{inner}{}\n", code.trim()));
    new_block.push(format!("{indent}except (ValueError, TypeError):\n"));
    if let Some(var) = default_var {
        new_block.push(format!("{inner}{var} = {default}\n"));
    } else {
        new_block.push(format!("{inner}pass  # handle non-numeric input\n"));
    }

    let mut new_lines: Vec<String> = lines[..idx].to_vec();
    new_lines.extend(new_block);
    new_lines.extend_from_slice(&lines[idx + 1..]);
    let diff = make_diff(lines, &new_lines, filepath);
    FixResult::success(
        &format!("Wrapped {func_name} in try/except (ValueError, TypeError)"),
        diff,
        new_lines,
    )
}

/// SEC-003: Replace shell=True with shell=False.
fn fix_sec003(filepath: &str, line_num: usize, _matched: &str, lines: &[String]) -> FixResult {
    let idx = line_num - 1;
    if idx >= lines.len() {
        return FixResult::err("Line out of range");
    }

    let line = &lines[idx];
    let new_line = line.replace("shell=True", "shell=False");
    if new_line == *line {
        return FixResult::err("Could not find shell=True on this line");
    }

    let mut new_lines: Vec<String> = lines[..idx].to_vec();
    new_lines.push(new_line);
    new_lines.extend_from_slice(&lines[idx + 1..]);
    let diff = make_diff(lines, &new_lines, filepath);
    FixResult::success("Changed shell=True to shell=False", diff, new_lines)
}

/// SEC-009: Replace unsafe YAML loading with safe_load().
fn fix_sec009(filepath: &str, line_num: usize, _matched: &str, lines: &[String]) -> FixResult {
    let idx = line_num - 1;
    if idx >= lines.len() {
        return FixResult::err("Line out of range");
    }

    let line = &lines[idx];
    let mut new_line = line.replace("yaml.load(", "yaml.safe_load(");
    // Remove Loader= arg
    let loader_re = Regex::new(r",\s*Loader\s*=\s*\w+\.?\w*").unwrap();
    new_line = loader_re.replace_all(&new_line, "").to_string();

    if new_line == *line {
        if line.contains("pickle.load") {
            return FixResult::err("pickle requires manual review — replace with json");
        }
        return FixResult::err("Could not auto-fix this pattern");
    }

    let mut new_lines: Vec<String> = lines[..idx].to_vec();
    new_lines.push(new_line);
    new_lines.extend_from_slice(&lines[idx + 1..]);
    let diff = make_diff(lines, &new_lines, filepath);
    FixResult::success("Replaced unsafe YAML loading with safe_load()", diff, new_lines)
}

// ── Fixer dispatch ─────────────────────────────────────────────────────

type FixerFn = fn(&str, usize, &str, &[String]) -> FixResult;

fn get_fixer(rule_id: &str) -> Option<FixerFn> {
    match rule_id {
        "PY-005" => Some(fix_py005),
        "PY-007" => Some(fix_py007),
        "QUAL-001" => Some(fix_qual001),
        "QUAL-003" => Some(fix_qual003),
        "QUAL-004" => Some(fix_qual004),
        "SEC-003" => Some(fix_sec003),
        "SEC-009" => Some(fix_sec009),
        _ => None,
    }
}

/// Generate a fix preview (diff) without modifying the file.
pub fn preview_fix(finding: &serde_json::Value) -> FixResult {
    let rule_id = finding.get("rule_id").and_then(|v| v.as_str()).unwrap_or("");
    let filepath = finding.get("file").and_then(|v| v.as_str()).unwrap_or("");
    let line_num = finding.get("line").and_then(|v| v.as_u64()).unwrap_or(0) as usize;
    let matched = finding.get("matched_text").and_then(|v| v.as_str()).unwrap_or("");

    let fixer = match get_fixer(rule_id) {
        Some(f) => f,
        None => {
            let hint = finding.get("fix_hint").and_then(|v| v.as_str()).unwrap_or("");
            return FixResult::err(&format!("No auto-fixer for {rule_id}. Fix hint: {hint}"));
        }
    };

    if !Path::new(filepath).is_file() {
        return FixResult::err(&format!("File not found: {filepath}"));
    }

    let lines = match read_file_lines(filepath) {
        Ok(l) => l,
        Err(e) => return FixResult::err(&e),
    };

    fixer(filepath, line_num, matched, &lines)
}

/// Apply a fix to a file on disk.
pub fn apply_fix(finding: &serde_json::Value) -> FixResult {
    let result = preview_fix(finding);
    if !result.fixable {
        return result;
    }

    let filepath = finding.get("file").and_then(|v| v.as_str()).unwrap_or("");
    if let Some(new_lines) = &result.new_lines {
        let content: String = new_lines.concat();
        if let Err(e) = std::fs::write(filepath, content) {
            return FixResult::err(&format!("Failed to write fix: {e}"));
        }
    }

    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_fixable_rules() {
        assert!(FIXABLE_RULES.contains(&"PY-005"));
        assert!(FIXABLE_RULES.contains(&"SEC-003"));
        assert!(!FIXABLE_RULES.contains(&"SEC-001"));
    }

    #[test]
    fn test_fix_qual001_bare_except() {
        let lines: Vec<String> = vec![
            "try:\n".into(),
            "    x = 1\n".into(),
            "except:\n".into(),
            "    pass\n".into(),
        ];
        let result = fix_qual001("test.py", 3, "except:", &lines);
        assert!(result.fixable);
        assert!(result.new_lines.unwrap()[2].contains("except Exception:"));
    }

    #[test]
    fn test_fix_sec003_shell_true() {
        let lines: Vec<String> = vec![
            "import subprocess\n".into(),
            "subprocess.run(cmd, shell=True)\n".into(),
        ];
        let result = fix_sec003("test.py", 2, "shell=True", &lines);
        assert!(result.fixable);
        assert!(result.new_lines.unwrap()[1].contains("shell=False"));
    }

    #[test]
    fn test_in_try_block() {
        let lines: Vec<String> = vec![
            "try:\n".into(),
            "    x = json.loads(data)\n".into(),
            "except:\n".into(),
            "    pass\n".into(),
        ];
        assert!(in_try_block(&lines, 1));
        assert!(!in_try_block(&lines, 0));
    }
}
