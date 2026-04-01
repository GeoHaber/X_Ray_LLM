//! Pure-Rust AST validators for reducing false positives.
//!
//! Uses **rustpython-parser** — a complete Python parser written in pure Rust
//! (no C compiler required). The AST types map 1:1 to Python's `ast` module.
//!
//! Each validator returns:
//! - `true`  → TRUE positive (keep the finding)
//! - `false` → false positive (suppress it)
//!
//! Design: fail-open. If parsing fails, the finding is kept.

use rustpython_ast::{self as ast, Expr, ExceptHandler, Mod, Stmt, Ranged};
use rustpython_parser::{self as parser, Mode};

// ── Python parsing ──────────────────────────────────────────────────────

/// Wrapper around a parsed Python module.
pub struct PythonAst {
    pub stmts: Vec<Stmt>,
}

/// Parse Python source into an AST. Returns `None` on syntax error (fail-open).
pub fn parse_python(source: &str) -> Option<PythonAst> {
    match parser::parse(source, Mode::Module, "<input>") {
        Ok(Mod::Module(module)) => Some(PythonAst {
            stmts: module.body,
        }),
        _ => None,
    }
}

// ── Helpers ─────────────────────────────────────────────────────────────

/// Walk all statements recursively, collecting references.
fn walk_stmts(stmts: &[Stmt]) -> Vec<&Stmt> {
    let mut result = Vec::new();
    for stmt in stmts {
        result.push(stmt);
        match stmt {
            Stmt::FunctionDef(f) => result.extend(walk_stmts(&f.body)),
            Stmt::AsyncFunctionDef(f) => result.extend(walk_stmts(&f.body)),
            Stmt::ClassDef(c) => result.extend(walk_stmts(&c.body)),
            Stmt::If(s) => {
                result.extend(walk_stmts(&s.body));
                result.extend(walk_stmts(&s.orelse));
            }
            Stmt::While(s) => {
                result.extend(walk_stmts(&s.body));
                result.extend(walk_stmts(&s.orelse));
            }
            Stmt::For(s) => {
                result.extend(walk_stmts(&s.body));
                result.extend(walk_stmts(&s.orelse));
            }
            Stmt::AsyncFor(s) => {
                result.extend(walk_stmts(&s.body));
                result.extend(walk_stmts(&s.orelse));
            }
            Stmt::Try(s) => {
                result.extend(walk_stmts(&s.body));
                for handler in &s.handlers {
                    let ExceptHandler::ExceptHandler(h) = handler;
                    result.extend(walk_stmts(&h.body));
                }
                result.extend(walk_stmts(&s.orelse));
                result.extend(walk_stmts(&s.finalbody));
            }
            Stmt::TryStar(s) => {
                result.extend(walk_stmts(&s.body));
                for handler in &s.handlers {
                    let ExceptHandler::ExceptHandler(h) = handler;
                    result.extend(walk_stmts(&h.body));
                }
                result.extend(walk_stmts(&s.orelse));
                result.extend(walk_stmts(&s.finalbody));
            }
            Stmt::With(s) => result.extend(walk_stmts(&s.body)),
            Stmt::AsyncWith(s) => result.extend(walk_stmts(&s.body)),
            _ => {}
        }
    }
    result
}

/// Get the 1-based starting line of a statement from source.
fn line_of_offset(source: &str, offset: usize) -> u32 {
    source[..offset.min(source.len())].matches('\n').count() as u32 + 1
}

/// Check if the given 1-based line falls inside a Try statement whose
/// handlers catch any of the listed exception names.
fn is_in_try_catching(stmts: &[Stmt], line: u32, exception_names: &[&str], source: &str) -> bool {
    for stmt in walk_stmts(stmts) {
        if let Stmt::Try(try_stmt) = stmt {
            // Determine try-body line range
            let body_start = try_stmt
                .body
                .first()
                .map(|s| line_of_offset(source, s.range().start().to_usize()))
                .unwrap_or(0);
            let body_end = try_stmt
                .body
                .last()
                .map(|s| line_of_offset(source, s.range().end().to_usize()))
                .unwrap_or(0);

            if line >= body_start && line <= body_end {
                for handler in &try_stmt.handlers {
                    let ExceptHandler::ExceptHandler(h) = handler;
                    if handler_catches(h, exception_names, source) {
                        return true;
                    }
                }
            }
        }
    }
    false
}

/// Check if an except handler catches any of the given exception names.
/// A bare `except:` (no type) matches everything.
fn handler_catches(
    handler: &ast::ExceptHandlerExceptHandler,
    names: &[&str],
    source: &str,
) -> bool {
    match &handler.type_ {
        None => true, // bare `except:` catches everything
        Some(expr) => expr_matches_exception(expr, names, source),
    }
}

/// Check if an exception type expression matches any of the given names.
fn expr_matches_exception(expr: &Expr, names: &[&str], source: &str) -> bool {
    match expr {
        Expr::Name(name) => names.iter().any(|n| name.id.as_str() == *n),
        Expr::Attribute(attr) => {
            let attr_name = attr.attr.as_str();
            if names.iter().any(|n| *n == attr_name) {
                return true;
            }
            // Check full dotted name from source
            let start = attr.range().start().to_usize();
            let end = attr.range().end().to_usize();
            if end <= source.len() {
                let text = &source[start..end];
                if names.iter().any(|n| *n == text) {
                    return true;
                }
            }
            false
        }
        Expr::Tuple(tuple) => tuple
            .elts
            .iter()
            .any(|elt| expr_matches_exception(elt, names, source)),
        _ => false,
    }
}

/// Check if the given 1-based line is inside any function definition.
fn is_inside_function(stmts: &[Stmt], line: u32, source: &str) -> bool {
    for stmt in walk_stmts(stmts) {
        match stmt {
            Stmt::FunctionDef(_) | Stmt::AsyncFunctionDef(_) => {
                let start = line_of_offset(source, stmt.range().start().to_usize());
                let end = line_of_offset(source, stmt.range().end().to_usize());
                if line >= start && line <= end {
                    return true;
                }
            }
            _ => {}
        }
    }
    false
}

// ── Validators ──────────────────────────────────────────────────────────

/// PY-005: `json.loads(...)` without try/except.
/// Suppress if properly handled inside try/except.
pub fn validate_py005(py: &PythonAst, source: &str, line: usize) -> bool {
    let names = &[
        "Exception",
        "BaseException",
        "JSONDecodeError",
        "ValueError",
        "json.JSONDecodeError",
    ];
    if is_in_try_catching(&py.stmts, line as u32, names, source) {
        return false;
    }
    true
}

/// PY-006: `global X` — suppress if at module level (no-op).
pub fn validate_py006(py: &PythonAst, source: &str, line: usize) -> bool {
    if is_inside_function(&py.stmts, line as u32, source) {
        return true; // inside function — keep
    }
    false // module-level — suppress
}

/// PY-007: `os.environ[]` — suppress if in try/except or assignment/deletion.
pub fn validate_py007(py: &PythonAst, source: &str, line: usize) -> bool {
    let lines: Vec<&str> = source.lines().collect();
    let line_0 = line.saturating_sub(1);

    if let Some(line_text) = lines.get(line_0) {
        let trimmed = line_text.trim();
        // Assignment: os.environ['KEY'] = value
        if trimmed.contains("os.environ[") && trimmed.contains("] =") {
            if let Some(pos) = trimmed.find("] =") {
                let after = &trimmed[pos + 3..];
                if !after.starts_with('=') {
                    return false;
                }
            }
        }
        // Deletion
        if trimmed.starts_with("del ") || trimmed.contains(".pop(") {
            return false;
        }
    }

    let names = &["Exception", "BaseException", "KeyError", "OSError"];
    if is_in_try_catching(&py.stmts, line as u32, names, source) {
        return false;
    }
    true
}

/// PY-008: `open()` without encoding — suppress for binary/method/encoding.
pub fn validate_py008(py: &PythonAst, source: &str, line: usize) -> bool {
    let _ = py; // line-based check is sufficient for these heuristics
    let lines: Vec<&str> = source.lines().collect();
    let line_0 = line.saturating_sub(1);

    if let Some(line_text) = lines.get(line_0) {
        let trimmed = line_text.trim();
        // Method call: obj.open() — not builtin
        if let Some(pos) = trimmed.find("open(") {
            if pos > 0 && trimmed.as_bytes()[pos - 1] == b'.' {
                return false;
            }
        }
        // Already has encoding=
        if trimmed.contains("encoding=") {
            return false;
        }
        // Binary mode patterns
        let binary = [
            "'rb'", "\"rb\"", "'wb'", "\"wb\"", "'ab'", "\"ab\"",
            "'r+b'", "\"r+b\"", "'w+b'", "\"w+b\"", "'rb+'", "\"rb+\"",
            "mode='rb'", "mode=\"rb\"", "mode='wb'", "mode=\"wb\"",
        ];
        for pat in &binary {
            if trimmed.contains(pat) {
                return false;
            }
        }
    }
    true
}

/// QUAL-003: `int(user_input)` — suppress if in try/except.
pub fn validate_qual003(py: &PythonAst, source: &str, line: usize) -> bool {
    let names = &["Exception", "BaseException", "ValueError", "TypeError"];
    if is_in_try_catching(&py.stmts, line as u32, names, source) {
        return false;
    }
    true
}

/// QUAL-004: `float(user_input)` — suppress if in try/except or argparse.
pub fn validate_qual004(py: &PythonAst, source: &str, line: usize) -> bool {
    let lines: Vec<&str> = source.lines().collect();
    let line_0 = line.saturating_sub(1);
    if let Some(line_text) = lines.get(line_0) {
        if line_text.contains("float(args.") || line_text.contains("float( args.") {
            return false;
        }
    }

    let names = &["Exception", "BaseException", "ValueError", "TypeError"];
    if is_in_try_catching(&py.stmts, line as u32, names, source) {
        return false;
    }
    true
}

// ── Dispatcher ──────────────────────────────────────────────────────────

/// Get the AST validator function for a rule ID, if one exists.
pub fn get_validator(rule_id: &str) -> Option<fn(&PythonAst, &str, usize) -> bool> {
    match rule_id {
        "PY-005" => Some(validate_py005),
        "PY-006" => Some(validate_py006),
        "PY-007" => Some(validate_py007),
        "PY-008" => Some(validate_py008),
        "QUAL-003" => Some(validate_qual003),
        "QUAL-004" => Some(validate_qual004),
        _ => None,
    }
}

// ── Tests ───────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_python_simple() {
        assert!(parse_python("x = 1\n").is_some());
    }

    #[test]
    fn test_parse_python_syntax_error() {
        assert!(parse_python("def (\n").is_none());
    }

    #[test]
    fn test_py005_no_try() {
        let src = "import json\ndata = json.loads(raw)\n";
        let py = parse_python(src).unwrap();
        assert!(validate_py005(&py, src, 2));
    }

    #[test]
    fn test_py005_in_try() {
        let src = "import json\ntry:\n    data = json.loads(raw)\nexcept json.JSONDecodeError:\n    data = {}\n";
        let py = parse_python(src).unwrap();
        assert!(!validate_py005(&py, src, 3));
    }

    #[test]
    fn test_py005_bare_except() {
        let src = "import json\ntry:\n    data = json.loads(raw)\nexcept:\n    data = {}\n";
        let py = parse_python(src).unwrap();
        assert!(!validate_py005(&py, src, 3));
    }

    #[test]
    fn test_py006_module_level() {
        let src = "global counter\ncounter = 0\n";
        let py = parse_python(src).unwrap();
        assert!(!validate_py006(&py, src, 1));
    }

    #[test]
    fn test_py006_in_function() {
        let src = "def increment():\n    global counter\n    counter += 1\n";
        let py = parse_python(src).unwrap();
        assert!(validate_py006(&py, src, 2));
    }

    #[test]
    fn test_py007_assignment() {
        let src = "import os\nos.environ['MY_KEY'] = 'value'\n";
        let py = parse_python(src).unwrap();
        assert!(!validate_py007(&py, src, 2));
    }

    #[test]
    fn test_py007_unguarded() {
        let src = "import os\nval = os.environ['MY_KEY']\n";
        let py = parse_python(src).unwrap();
        assert!(validate_py007(&py, src, 2));
    }

    #[test]
    fn test_py007_in_try() {
        let src = "import os\ntry:\n    val = os.environ['MY_KEY']\nexcept KeyError:\n    val = 'default'\n";
        let py = parse_python(src).unwrap();
        assert!(!validate_py007(&py, src, 3));
    }

    #[test]
    fn test_py008_method_call() {
        let src = "img = Image.open('photo.png')\n";
        let py = parse_python(src).unwrap();
        assert!(!validate_py008(&py, src, 1));
    }

    #[test]
    fn test_py008_binary_mode() {
        let src = "f = open('data.bin', 'rb')\n";
        let py = parse_python(src).unwrap();
        assert!(!validate_py008(&py, src, 1));
    }

    #[test]
    fn test_py008_no_encoding() {
        let src = "f = open('data.txt', 'r')\n";
        let py = parse_python(src).unwrap();
        assert!(validate_py008(&py, src, 1));
    }

    #[test]
    fn test_qual003_no_try() {
        let src = "val = int(user_input)\n";
        let py = parse_python(src).unwrap();
        assert!(validate_qual003(&py, src, 1));
    }

    #[test]
    fn test_qual003_in_try() {
        let src = "try:\n    val = int(user_input)\nexcept ValueError:\n    val = 1\n";
        let py = parse_python(src).unwrap();
        assert!(!validate_qual003(&py, src, 2));
    }

    #[test]
    fn test_qual004_argparse() {
        let src = "rate = float(args.rate)\n";
        let py = parse_python(src).unwrap();
        assert!(!validate_qual004(&py, src, 1));
    }

    #[test]
    fn test_get_validator_known() {
        assert!(get_validator("PY-005").is_some());
        assert!(get_validator("QUAL-004").is_some());
    }

    #[test]
    fn test_get_validator_unknown() {
        assert!(get_validator("SEC-001").is_none());
    }
}
