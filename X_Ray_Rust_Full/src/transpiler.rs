// src/transpiler.rs — Python → Rust transpiler
//
// Port of the transpilation logic from Analysis/auto_rustify.py
// Converts Python source code into Rust source code using regex-based
// expression rewriting and line-by-line statement translation.

use regex::Regex;
use std::collections::HashMap;

use crate::types::FunctionRecord;

// ═══════════════════════════════════════════════════════════════════════════
//  Type mapping: Python → Rust
// ═══════════════════════════════════════════════════════════════════════════

fn base_type_map() -> HashMap<&'static str, &'static str> {
    let mut m = HashMap::new();
    m.insert("int", "i64");
    m.insert("float", "f64");
    m.insert("str", "String");
    m.insert("bool", "bool");
    m.insert("bytes", "Vec<u8>");
    m.insert("list", "Vec");
    m.insert("dict", "HashMap");
    m.insert("set", "HashSet");
    m.insert("tuple", "tuple");
    m.insert("None", "()");
    m.insert("Optional", "Option");
    m.insert("List", "Vec");
    m.insert("Dict", "HashMap");
    m.insert("Set", "HashSet");
    m.insert("Tuple", "tuple");
    m.insert("Any", "String");
    m
}

/// Convert a Python type annotation string to a Rust type string.
pub fn py_type_to_rust(py_type: &str) -> String {
    let py_type = py_type.trim();
    if py_type.is_empty() {
        return "String".to_string();
    }

    let map = base_type_map();

    // Optional[X]
    let re_optional = Regex::new(r"^Optional\[(.+)\]$").unwrap();
    if let Some(caps) = re_optional.captures(py_type) {
        return format!("Option<{}>", py_type_to_rust(&caps[1]));
    }

    // List[X] or Set[X]
    let re_list_set = Regex::new(r"^(List|Set)\[(.+)\]$").unwrap();
    if let Some(caps) = re_list_set.captures(py_type) {
        let container = if &caps[1] == "List" { "Vec" } else { "HashSet" };
        return format!("{}<{}>", container, py_type_to_rust(&caps[2]));
    }

    // Dict[K, V]
    let re_dict = Regex::new(r"^Dict\[(.+?),\s*(.+)\]$").unwrap();
    if let Some(caps) = re_dict.captures(py_type) {
        return format!(
            "HashMap<{}, {}>",
            py_type_to_rust(&caps[1]),
            py_type_to_rust(&caps[2])
        );
    }

    // Tuple[X, Y, ...]
    let re_tuple = Regex::new(r"^Tuple\[(.+)\]$").unwrap();
    if let Some(caps) = re_tuple.captures(py_type) {
        let parts: Vec<String> = caps[1]
            .split(',')
            .map(|p| py_type_to_rust(p.trim()))
            .collect();
        return format!("({})", parts.join(", "));
    }

    // Direct lookup
    if let Some(&rust_type) = map.get(py_type) {
        return rust_type.to_string();
    }

    // Unknown → String (safe fallback for binary mode)
    "String".to_string()
}

// ═══════════════════════════════════════════════════════════════════════════
//  Expression rewriting: Python expr → Rust expr
// ═══════════════════════════════════════════════════════════════════════════

/// Convert a Python expression string to a Rust expression string.
pub fn rustify_expr(expr: &str) -> String {
    let mut e = expr.to_string();

    // Single-quoted strings → double-quoted
    // Note: Rust regex doesn't support lookbehind, so we capture optional preceding non-word char
    let re_sq = Regex::new(r#"(^|[^a-zA-Z0-9_])'([^']*?)'"#).unwrap();
    e = re_sq
        .replace_all(&e, |caps: &regex::Captures| {
            let prefix = &caps[1];
            let inner = caps[2].replace('"', "\\\"");
            format!("{}\"{}\"", prefix, inner)
        })
        .to_string();

    // Booleans
    e = e.replace("True", "true");
    e = e.replace("False", "false");

    // Logical operators
    e = e.replace(" and ", " && ");
    e = e.replace(" or ", " || ");
    // "not " at start or after space/paren
    let re_not = Regex::new(r"\bnot\s+").unwrap();
    e = re_not.replace_all(&e, "!").to_string();

    // len(x) → x.len()
    let re_len = Regex::new(r"\blen\((\w+)\)").unwrap();
    e = re_len.replace_all(&e, "$1.len()").to_string();

    // f-string → format!
    let re_fstr_dq = Regex::new(r#"f"([^"]*)""#).unwrap();
    e = re_fstr_dq.replace_all(&e, "format!(\"$1\")").to_string();
    let re_fstr_sq = Regex::new(r"f'([^']*)'").unwrap();
    e = re_fstr_sq.replace_all(&e, "format!(\"$1\")").to_string();

    // range()
    let re_range1 = Regex::new(r"range\((\w+)\)").unwrap();
    e = re_range1.replace_all(&e, "0..$1").to_string();
    let re_range2 = Regex::new(r"range\((\w+),\s*(\w+)\)").unwrap();
    e = re_range2.replace_all(&e, "$1..$2").to_string();

    // isinstance → comment
    let re_isinstance = Regex::new(r"isinstance\((\w+),\s*(\w+)\)").unwrap();
    e = re_isinstance
        .replace_all(&e, "/* isinstance($1, $2) */ true")
        .to_string();
    // isinstance with tuple of types
    let re_isinstance2 = Regex::new(r"isinstance\((\w+),\s*\(([^)]+)\)\)").unwrap();
    e = re_isinstance2
        .replace_all(&e, "/* isinstance($1, ($2)) */ true")
        .to_string();

    // Python `in` operator for containers → .contains()
    let re_in = Regex::new(r#"(\w+)\s+in\s+(\w+)"#).unwrap();
    e = re_in.replace_all(&e, "$2.contains(&$1)").to_string();
    // "x" in string → string.contains("x")
    let re_str_in = Regex::new(r#""([^"]+)"\s+in\s+(\w+)"#).unwrap();
    e = re_str_in.replace_all(&e, "$2.contains(\"$1\")").to_string();
    // Python `not in` → !.contains()
    let re_notin = Regex::new(r#"(\w+)\s+not\s+in\s+(\w+)"#).unwrap();
    e = re_notin.replace_all(&e, "!$2.contains(&$1)").to_string();

    // any() / all() → .any() / .all() (best effort)
    let re_any = Regex::new(r"\bany\(([^)]+)\)").unwrap();
    e = re_any.replace_all(&e, "/* any($1) */ true").to_string();
    let re_all = Regex::new(r"\ball\(([^)]+)\)").unwrap();
    e = re_all.replace_all(&e, "/* all($1) */ true").to_string();

    // str() cast → .to_string()
    let re_str_cast = Regex::new(r"\bstr\((\w+)\)").unwrap();
    e = re_str_cast.replace_all(&e, "$1.to_string()").to_string();

    // int() cast → as i64 (best effort)
    let re_int_cast = Regex::new(r"\bint\((\w+)\)").unwrap();
    e = re_int_cast.replace_all(&e, "$1 as i64").to_string();

    // float() cast → as f64
    let re_float_cast = Regex::new(r"\bfloat\((\w+)\)").unwrap();
    e = re_float_cast.replace_all(&e, "$1 as f64").to_string();

    // Method rewrites
    e = e.replace(".append(", ".push(");
    e = e.replace(".extend(", ".extend(");
    e = e.replace(".items()", ".iter()");
    e = e.replace(".keys()", ".keys()");
    e = e.replace(".values()", ".values()");
    e = e.replace(".strip()", ".trim()");
    e = e.replace(".lstrip()", ".trim_start()");
    e = e.replace(".rstrip()", ".trim_end()");
    e = e.replace(".lower()", ".to_lowercase()");
    e = e.replace(".upper()", ".to_uppercase()");
    e = e.replace(".startswith(", ".starts_with(");
    e = e.replace(".endswith(", ".ends_with(");
    // .replace and .split stay the same in Rust

    // elif → else if
    e = e.replace("elif", "else if");

    // print(...) → println!(...)
    let re_print = Regex::new(r"\bprint\((.+)\)").unwrap();
    e = re_print.replace_all(&e, "println!($1)").to_string();

    // Python None → Rust None (for Option types)
    e = e.replace("None", "None");

    // dict() → HashMap::new(), list() → Vec::new(), set() → HashSet::new()
    e = e.replace("dict()", "HashMap::new()");
    e = e.replace("list()", "Vec::new()");
    e = e.replace("set()", "HashSet::new()");

    // [] → vec![] for empty lists (only standalone)
    if e.trim() == "[]" {
        e = "vec![]".to_string();
    }
    // {} → HashMap::new() (only standalone, risky but common)
    if e.trim() == "{}" {
        e = "HashMap::new()".to_string();
    }

    // Python # comment within expression → //
    if let Some(hash_pos) = e.find('#') {
        let before = &e[..hash_pos];
        let after = &e[hash_pos + 1..];
        // Only convert if # is outside of a string
        if before.matches('"').count() % 2 == 0 {
            e = format!("{}//{}", before, after);
        }
    }

    e
}

/// Map a Python operator string to its Rust equivalent.
fn rust_op(op: &str) -> &str {
    match op.trim() {
        "+" | "Add" => "+",
        "-" | "Sub" => "-",
        "*" | "Mult" => "*",
        "/" | "Div" => "/",
        "%" | "Mod" => "%",
        "**" | "Pow" => ".pow",
        "|" | "BitOr" => "|",
        "&" | "BitAnd" => "&",
        "^" | "BitXor" => "^",
        "<<" | "LShift" => "<<",
        ">>" | "RShift" => ">>",
        "//" | "FloorDiv" => "/",
        _ => "+",
    }
}

// ═══════════════════════════════════════════════════════════════════════════
//  Statement-level translation: Python lines → Rust lines
// ═══════════════════════════════════════════════════════════════════════════

/// Determine the indentation level of a line (in spaces).
fn indent_of(line: &str) -> usize {
    line.len() - line.trim_start().len()
}

/// A simplified Python "statement" parsed from source lines.
enum PyStmt {
    Return(String),           // return <expr>
    If(String),               // if <test>:
    Elif(String),             // elif <test>:
    Else,                     // else:
    For(String, String),      // for <target> in <iter>:
    While(String),            // while <test>:
    Assign(String, String),   // <target> = <value>
    AugAssign(String, String, String), // <target> <op>= <value>
    Pass,
    Break,
    Continue,
    Assert(String),           // assert <test>
    Raise(String),            // raise <exc>
    Try,                      // try:
    Except(String),           // except <type>:
    Finally,                  // finally:
    With(String),             // with <items>:
    FuncDef(String),          // def <name>(...):
    ClassDef(String),         // class <name>:
    Docstring(String),        // """..."""
    ExprStmt(String),         // <expression>
    Comment(String),          // # comment
    Blank,
}

/// Parse a trimmed Python line into a PyStmt.
fn classify_line(trimmed: &str) -> PyStmt {
    if trimmed.is_empty() {
        return PyStmt::Blank;
    }
    if trimmed.starts_with('#') {
        return PyStmt::Comment(trimmed.to_string());
    }
    // Docstrings
    if (trimmed.starts_with("\"\"\"") || trimmed.starts_with("'''"))
        && trimmed.len() >= 6
    {
        return PyStmt::Docstring(trimmed.to_string());
    }
    if trimmed.starts_with("return ") || trimmed == "return" {
        let expr = trimmed.strip_prefix("return").unwrap_or("").trim().to_string();
        return PyStmt::Return(expr);
    }
    if trimmed.starts_with("if ") && trimmed.ends_with(':') {
        let test = trimmed[3..trimmed.len() - 1].trim().to_string();
        return PyStmt::If(test);
    }
    if trimmed.starts_with("elif ") && trimmed.ends_with(':') {
        let test = trimmed[5..trimmed.len() - 1].trim().to_string();
        return PyStmt::Elif(test);
    }
    if trimmed == "else:" {
        return PyStmt::Else;
    }
    if trimmed.starts_with("for ") && trimmed.contains(" in ") && trimmed.ends_with(':') {
        let body = &trimmed[4..trimmed.len() - 1];
        if let Some(idx) = body.find(" in ") {
            let target = body[..idx].trim().to_string();
            let iter_expr = body[idx + 4..].trim().to_string();
            return PyStmt::For(target, iter_expr);
        }
    }
    if trimmed.starts_with("while ") && trimmed.ends_with(':') {
        let test = trimmed[6..trimmed.len() - 1].trim().to_string();
        return PyStmt::While(test);
    }
    if trimmed == "pass" {
        return PyStmt::Pass;
    }
    if trimmed == "break" {
        return PyStmt::Break;
    }
    if trimmed == "continue" {
        return PyStmt::Continue;
    }
    if trimmed.starts_with("assert ") {
        return PyStmt::Assert(trimmed[7..].trim().to_string());
    }
    if trimmed.starts_with("raise ") || trimmed == "raise" {
        let exc = trimmed.strip_prefix("raise").unwrap_or("").trim().to_string();
        return PyStmt::Raise(exc);
    }
    if trimmed == "try:" {
        return PyStmt::Try;
    }
    if trimmed.starts_with("except") && trimmed.ends_with(':') {
        let exc = trimmed
            .strip_prefix("except")
            .unwrap_or("")
            .trim_end_matches(':')
            .trim()
            .to_string();
        return PyStmt::Except(if exc.is_empty() {
            "Exception".to_string()
        } else {
            exc
        });
    }
    if trimmed == "finally:" {
        return PyStmt::Finally;
    }
    if trimmed.starts_with("with ") && trimmed.ends_with(':') {
        let items = trimmed[5..trimmed.len() - 1].trim().to_string();
        return PyStmt::With(items);
    }
    if (trimmed.starts_with("def ") || trimmed.starts_with("async def "))
        && trimmed.ends_with(':')
    {
        let name = if trimmed.starts_with("async def ") {
            trimmed[10..].split('(').next().unwrap_or("unknown")
        } else {
            trimmed[4..].split('(').next().unwrap_or("unknown")
        };
        return PyStmt::FuncDef(name.trim().to_string());
    }
    if trimmed.starts_with("class ") && trimmed.ends_with(':') {
        let name = trimmed[6..]
            .split(&['(', ':'][..])
            .next()
            .unwrap_or("Unknown")
            .trim()
            .to_string();
        return PyStmt::ClassDef(name);
    }

    // Augmented assignment: +=, -=, *=, /=, %=, //=, **=, |=, &=, ^=, <<=, >>=
    let aug_ops = ["//=", "**=", "<<=", ">>=", "+=", "-=", "*=", "/=", "%=", "|=", "&=", "^="];
    for op in aug_ops {
        if let Some(idx) = trimmed.find(op) {
            let target = trimmed[..idx].trim().to_string();
            let base_op = &op[..op.len() - 1]; // strip trailing '='
            let value = trimmed[idx + op.len()..].trim().to_string();
            return PyStmt::AugAssign(target, base_op.to_string(), value);
        }
    }

    // Plain assignment (= but not == or !=)
    if let Some(idx) = find_assignment(trimmed) {
        let target = trimmed[..idx].trim().to_string();
        let value = trimmed[idx + 1..].trim().to_string();
        return PyStmt::Assign(target, value);
    }

    // Expression statement
    PyStmt::ExprStmt(trimmed.to_string())
}

/// Find the index of a plain `=` that is an assignment (not `==`, `!=`, `<=`, `>=`).
fn find_assignment(line: &str) -> Option<usize> {
    let chars: Vec<char> = line.chars().collect();
    let mut depth = 0i32; // track parens/brackets
    for i in 0..chars.len() {
        match chars[i] {
            '(' | '[' | '{' => depth += 1,
            ')' | ']' | '}' => depth -= 1,
            '=' if depth == 0 => {
                // Check it's not ==, !=, <=, >=
                let prev = if i > 0 { chars[i - 1] } else { ' ' };
                let next = if i + 1 < chars.len() { chars[i + 1] } else { ' ' };
                if next != '=' && prev != '!' && prev != '<' && prev != '>' && prev != '=' {
                    return Some(i);
                }
            }
            _ => {}
        }
    }
    None
}

// ═══════════════════════════════════════════════════════════════════════════
//  Main transpile entry points
// ═══════════════════════════════════════════════════════════════════════════

/// Transpile a FunctionRecord's Python code to Rust.
///
/// Returns a complete Rust function definition as a string.
pub fn transpile_function(func: &FunctionRecord) -> String {
    let code = &func.code;
    let lines: Vec<&str> = code.lines().collect();

    if lines.is_empty() {
        return format!(
            "fn {}() {{\n    todo!(\"empty source\")\n}}",
            func.name
        );
    }

    // 1. Parse function signature from first line
    let (params_rust, ret_rust) = parse_signature(func);

    // 2. Build function header
    let mut out = Vec::new();
    out.push(format!("fn {}({}) -> {} {{", func.name, params_rust, ret_rust));

    // 3. Translate the body
    // Skip the def line and any immediate docstring
    let body_start = find_body_start(&lines);
    let body_lines = &lines[body_start..];

    if body_lines.is_empty() {
        out.push("    todo!(\"empty body\")".to_string());
    } else {
        // Determine base indentation
        let base_indent = body_lines
            .iter()
            .filter(|l| !l.trim().is_empty())
            .map(|l| indent_of(l))
            .min()
            .unwrap_or(4);

        let translated = translate_body(body_lines, base_indent, &ret_rust);
        out.extend(translated);

        // Ensure we have a final return
        if !has_terminal_return(&out) {
            if ret_rust == "()" {
                // No explicit return needed for unit
            } else {
                out.push(format!(
                    "    todo!(\"return value of type {}\")",
                    ret_rust
                ));
            }
        }
    }

    out.push("}".to_string());

    // 4. Post-process: balance braces
    balance_braces(&mut out);

    out.join("\n")
}

/// Post-process output lines to ensure braces are balanced.
/// Counts `{` and `}` in non-comment lines and adds/removes closing braces.
fn balance_braces(lines: &mut Vec<String>) {
    let mut depth: i32 = 0;
    for line in lines.iter() {
        let trimmed = line.trim();
        // Skip full-line comments
        if trimmed.starts_with("//") {
            continue;
        }
        for ch in trimmed.chars() {
            if ch == '{' { depth += 1; }
            if ch == '}' { depth -= 1; }
        }
    }

    // If depth > 0, we have unclosed braces — add closing ones
    while depth > 0 {
        // Insert before the last line (which is the function's closing `}`)
        let last = lines.pop().unwrap_or_else(|| "}".to_string());
        lines.push("}".to_string());
        lines.push(last);
        depth -= 1;
    }

    // If depth < 0, we have extra closing braces — remove from the end
    while depth < 0 {
        // Find and remove an extra `}` from the end
        if let Some(pos) = lines.iter().rposition(|l| l.trim() == "}") {
            lines.remove(pos);
            depth += 1;
        } else {
            break;
        }
    }
}
fn parse_signature(func: &FunctionRecord) -> (String, String) {
    // Try to extract type annotations from the code's def line
    let annotation_map = extract_annotations_from_def(&func.code);

    // Parameters — filter out garbage entries from bad param parsing
    let params: Vec<String> = func
        .parameters
        .iter()
        .filter(|p| {
            *p != "self" && *p != "cls"
                && !p.contains('[') && !p.contains(']')
                && !p.contains('(') && !p.contains(')')
                && !p.contains('{') && !p.contains('}')
                && !p.contains(' ') && !p.contains('=')
                && !p.contains('.')
                && p.chars().all(|c| c.is_alphanumeric() || c == '_' || c == '*')
        })
        .map(|p| {
            let clean = p.trim_start_matches('*');
            let rust_type = if let Some(py_type) = annotation_map.get(clean) {
                // Have an explicit Python annotation — convert it
                py_type_to_rust(py_type)
            } else {
                // Fallback to name-based heuristic
                infer_param_type(clean)
            };
            format!("{}: {}", sanitize_name(clean), rust_type)
        })
        .collect();

    // Return type
    let ret_type = func
        .return_type
        .as_ref()
        .map(|rt| py_type_to_rust(rt))
        .unwrap_or_else(|| "()".to_string());

    (params.join(", "), ret_type)
}

/// Extract parameter type annotations from a Python def line.
/// Returns a map from param name → Python type string.
fn extract_annotations_from_def(code: &str) -> std::collections::HashMap<&str, &str> {
    let mut map = std::collections::HashMap::new();
    // Find the def line (may span multiple lines)
    let mut def_part = String::new();
    for line in code.lines() {
        let trimmed = line.trim();
        if def_part.is_empty() {
            if trimmed.starts_with("def ") || trimmed.starts_with("async def ") {
                def_part = trimmed.to_string();
            } else {
                continue;
            }
        } else {
            // continuation of a multi-line def
            def_part.push(' ');
            def_part.push_str(trimmed);
        }
        if def_part.contains("):") || def_part.contains(") ->") {
            break; // We have the full signature
        }
    }

    // Now parse annotations from the def line within the original code
    // We work with the original code slice to return &str references
    let first_paren = match code.find('(') {
        Some(p) => p,
        None => return map,
    };
    let last_paren = match code[first_paren..].find(')') {
        Some(p) => first_paren + p,
        None => return map,
    };
    let params_str = &code[first_paren + 1..last_paren];

    // Split by comma, handling nested brackets
    let mut depth = 0i32;
    let mut start = 0;
    let bytes = params_str.as_bytes();
    for i in 0..=bytes.len() {
        let at_end = i == bytes.len();
        let ch = if at_end { b',' } else { bytes[i] };
        match ch {
            b'(' | b'[' | b'{' => depth += 1,
            b')' | b']' | b'}' => depth -= 1,
            b',' if depth == 0 => {
                let param = params_str[start..i].trim();
                // Check for annotation: "name: type" or "name: type = default"
                if let Some(colon) = param.find(':') {
                    let pname = param[..colon].trim();
                    let rest = param[colon + 1..].trim();
                    // Strip default value
                    let py_type = if let Some(eq) = find_default_eq(rest) {
                        rest[..eq].trim()
                    } else {
                        rest
                    };
                    if !pname.is_empty() && !py_type.is_empty() {
                        map.insert(pname, py_type);
                    }
                }
                start = i + 1;
            }
            _ => {}
        }
    }
    map
}

/// Find the `=` of a default value in a param annotation, skipping `==`.
fn find_default_eq(s: &str) -> Option<usize> {
    let chars: Vec<char> = s.chars().collect();
    let mut depth = 0i32;
    for i in 0..chars.len() {
        match chars[i] {
            '(' | '[' | '{' => depth += 1,
            ')' | ']' | '}' => depth -= 1,
            '=' if depth == 0 => {
                let next = if i + 1 < chars.len() { chars[i + 1] } else { ' ' };
                let prev = if i > 0 { chars[i - 1] } else { ' ' };
                if next != '=' && prev != '!' && prev != '<' && prev != '>' && prev != '=' {
                    return Some(i);
                }
            }
            _ => {}
        }
    }
    None
}

/// Infer a Rust type from a Python parameter name.
fn infer_param_type(name: &str) -> String {
    let lower = name.to_lowercase();
    if lower.contains("path") || lower.contains("file") || lower.contains("dir") {
        return "&str".to_string();
    }
    if lower.contains("name")
        || lower.contains("text")
        || lower.contains("msg")
        || lower.contains("code")
        || lower.contains("source")
        || lower.contains("line")
        || lower.contains("pattern")
        || lower == "s"
    {
        return "&str".to_string();
    }
    if lower.contains("count")
        || lower.contains("size")
        || lower.contains("num")
        || lower.contains("index")
        || lower == "n"
        || lower == "i"
        || lower == "j"
    {
        return "usize".to_string();
    }
    if lower.contains("flag") || lower.contains("enable") || lower.contains("verbose") {
        return "bool".to_string();
    }
    if lower.contains("items") || lower.contains("list") || lower.contains("values") {
        return "&[String]".to_string();
    }
    // Default
    "&str".to_string()
}

/// Sanitize a Python variable name for Rust (handle reserved words).
fn sanitize_name(name: &str) -> String {
    match name {
        "type" => "r#type".to_string(),
        "match" => "r#match".to_string(),
        "ref" => "r#ref".to_string(),
        "self" => "self_".to_string(),
        "mod" => "r#mod".to_string(),
        "fn" => "fn_".to_string(),
        "use" => "use_".to_string(),
        "impl" => "impl_".to_string(),
        "struct" => "struct_".to_string(),
        "enum" => "enum_".to_string(),
        "trait" => "trait_".to_string(),
        "pub" => "pub_".to_string(),
        "mut" => "mut_".to_string(),
        "let" => "let_".to_string(),
        "loop" => "loop_".to_string(),
        "move" => "move_".to_string(),
        "async" => "async_".to_string(),
        "await" => "await_".to_string(),
        "where" => "where_".to_string(),
        "crate" => "crate_".to_string(),
        "super" => "super_".to_string(),
        _ => name.to_string(),
    }
}

/// Find where the function body starts (after def line + docstring).
fn find_body_start(lines: &[&str]) -> usize {
    let mut i = 0;

    // Skip the def line(s) — handle multi-line defs
    while i < lines.len() {
        let trimmed = lines[i].trim();
        i += 1;
        if trimmed.ends_with(':') {
            break;
        }
    }

    // Skip docstring if present
    if i < lines.len() {
        let trimmed = lines[i].trim();
        if trimmed.starts_with("\"\"\"") || trimmed.starts_with("'''") {
            let delim = &trimmed[..3];
            if trimmed.len() >= 6 && trimmed.ends_with(delim) {
                // Single-line docstring
                i += 1;
            } else {
                // Multi-line docstring — find the end
                i += 1;
                while i < lines.len() {
                    if lines[i].contains(delim) {
                        i += 1;
                        break;
                    }
                    i += 1;
                }
            }
        }
    }

    i
}

/// Join Python continuation lines (lines where parens/brackets/braces are unbalanced).
/// Preserves the indentation of the first line for each joined group.
fn join_continuation_lines(lines: &[&str]) -> Vec<String> {
    let mut joined = Vec::new();
    let mut i = 0;
    while i < lines.len() {
        let line = lines[i];
        let trimmed = line.trim();

        // Count open/close delimiters
        let mut depth: i32 = 0;
        for ch in trimmed.chars() {
            match ch {
                '(' | '[' | '{' => depth += 1,
                ')' | ']' | '}' => depth -= 1,
                '#' => break, // stop counting at comments
                _ => {}
            }
        }

        if depth > 0 {
            // Continuation: join subsequent lines until balanced
            let indent_prefix = &line[..indent_of(line)];
            let mut combined = trimmed.to_string();
            i += 1;
            while i < lines.len() && depth > 0 {
                let cont = lines[i].trim();
                for ch in cont.chars() {
                    match ch {
                        '(' | '[' | '{' => depth += 1,
                        ')' | ']' | '}' => depth -= 1,
                        '#' => break,
                        _ => {}
                    }
                }
                combined.push(' ');
                combined.push_str(cont);
                i += 1;
            }
            // Re-attach the original indentation
            joined.push(format!("{}{}", indent_prefix, combined));
        } else if trimmed.ends_with('\\') {
            // Explicit line continuation with backslash
            let indent_prefix = &line[..indent_of(line)];
            let mut combined = trimmed.trim_end_matches('\\').to_string();
            i += 1;
            while i < lines.len() {
                let cont = lines[i].trim();
                combined.push(' ');
                if cont.ends_with('\\') {
                    combined.push_str(cont.trim_end_matches('\\'));
                    i += 1;
                } else {
                    combined.push_str(cont);
                    i += 1;
                    break;
                }
            }
            joined.push(format!("{}{}", indent_prefix, combined));
        } else {
            joined.push(line.to_string());
            i += 1;
        }
    }
    joined
}

/// Translate Python body lines to Rust lines.
fn translate_body(lines: &[&str], base_indent: usize, ret_type: &str) -> Vec<String> {
    // Pre-process: join continuation lines (unbalanced parens/brackets)
    let joined = join_continuation_lines(lines);
    let joined_refs: Vec<&str> = joined.iter().map(|s| s.as_str()).collect();
    let lines = &joined_refs[..];

    let mut result = Vec::new();

    let mut i = 0;
    while i < lines.len() {
        let line = lines[i];
        let trimmed = line.trim();

        if trimmed.is_empty() {
            result.push(String::new());
            i += 1;
            continue;
        }

        let current_indent = indent_of(line);
        let rust_indent_level = if current_indent >= base_indent {
            1 + (current_indent - base_indent) / 4
        } else {
            1
        };
        let pad = "    ".repeat(rust_indent_level);

        let stmt = classify_line(trimmed);

        match &stmt {
            PyStmt::Return(expr) => {
                if expr.is_empty() {
                    result.push(format!("{}return;", pad));
                } else {
                    let rust_expr = rustify_expr(expr);
                    // Coerce string literal to .to_string() if return type is String
                    let rust_expr = maybe_to_string(&rust_expr, ret_type);
                    result.push(format!("{}return {};", pad, rust_expr));
                }
            }
            PyStmt::If(test) => {
                result.push(format!("{}if {} {{", pad, rustify_expr(test)));
            }
            PyStmt::Elif(test) => {
                result.push(format!("{}}} else if {} {{", pad, rustify_expr(test)));
            }
            PyStmt::Else => {
                result.push(format!("{}}} else {{", pad));
            }
            PyStmt::For(target, iter_expr) => {
                result.push(format!(
                    "{}for {} in {} {{",
                    pad,
                    sanitize_name(target),
                    rustify_expr(iter_expr)
                ));
            }
            PyStmt::While(test) => {
                result.push(format!("{}while {} {{", pad, rustify_expr(test)));
            }
            PyStmt::Assign(target, value) => {
                result.push(format!(
                    "{}let mut {} = {};",
                    pad,
                    sanitize_name(target),
                    rustify_expr(value)
                ));
            }
            PyStmt::AugAssign(target, op, value) => {
                let rop = rust_op(op);
                result.push(format!(
                    "{}{} {}= {};",
                    pad,
                    sanitize_name(target),
                    rop,
                    rustify_expr(value)
                ));
            }
            PyStmt::Pass => {
                result.push(format!("{}// pass", pad));
            }
            PyStmt::Break => {
                result.push(format!("{}break;", pad));
            }
            PyStmt::Continue => {
                result.push(format!("{}continue;", pad));
            }
            PyStmt::Assert(test) => {
                result.push(format!("{}assert!({});", pad, rustify_expr(test)));
            }
            PyStmt::Raise(exc) => {
                if exc.is_empty() {
                    result.push(format!("{}panic!(\"raised\");", pad));
                } else {
                    let escaped = exc.replace('"', "\\\"");
                    result.push(format!("{}panic!(\"{}\");", pad, escaped));
                }
            }
            PyStmt::Try => {
                result.push(format!("{}// try {{", pad));
            }
            PyStmt::Except(exc) => {
                result.push(format!("{}// }} catch {} {{", pad, exc));
            }
            PyStmt::Finally => {
                result.push(format!("{}// }} finally {{", pad));
            }
            PyStmt::With(items) => {
                result.push(format!("{}// with {} {{", pad, items));
            }
            PyStmt::FuncDef(name) => {
                result.push(format!("{}// TODO: nested fn {}()", pad, name));
                // Skip the nested function body
                i = skip_block(lines, i, current_indent);
                continue;
            }
            PyStmt::ClassDef(name) => {
                result.push(format!("{}// TODO: nested class {}", pad, name));
                i = skip_block(lines, i, current_indent);
                continue;
            }
            PyStmt::Docstring(_) => {
                // Skip docstrings
            }
            PyStmt::ExprStmt(expr) => {
                result.push(format!("{}{};", pad, rustify_expr(expr)));
            }
            PyStmt::Comment(c) => {
                let rust_comment = c.replacen('#', "//", 1);
                result.push(format!("{}{}", pad, rust_comment));
            }
            PyStmt::Blank => {}
        }

        // Handle closing braces for blocks that just ended
        // Look ahead: if next line's indent drops, close braces
        if i + 1 < lines.len() {
            let next_trimmed = lines[i + 1].trim();
            if !next_trimmed.is_empty() {
                let next_indent = indent_of(lines[i + 1]);
                // We need to close braces for blocks ending here
                // If the current was a block-opening statement, don't close yet
                let is_block_open = matches!(
                    &stmt,
                    PyStmt::If(_)
                        | PyStmt::Elif(_)
                        | PyStmt::Else
                        | PyStmt::For(_, _)
                        | PyStmt::While(_)
                        | PyStmt::Try
                        | PyStmt::Except(_)
                        | PyStmt::Finally
                        | PyStmt::With(_)
                );

                // Check if next line is elif/else/except/finally — they emit
                // their own closing `}` so we must NOT auto-close here.
                let next_stmt = classify_line(next_trimmed);
                let next_is_continuation = matches!(
                    &next_stmt,
                    PyStmt::Elif(_)
                        | PyStmt::Else
                        | PyStmt::Except(_)
                        | PyStmt::Finally
                );

                if !is_block_open && !next_is_continuation && next_indent < current_indent {
                    // Close blocks
                    let levels_to_close = (current_indent - next_indent) / 4;
                    for j in 0..levels_to_close {
                        let close_level = rust_indent_level - 1 - j;
                        if close_level >= 1 {
                            result.push(format!("{}}}", "    ".repeat(close_level)));
                        }
                    }
                }
            }
        }

        i += 1;
    }

    result
}

/// Skip a Python block (nested def, class) by tracking indentation.
fn skip_block(lines: &[&str], start: usize, block_indent: usize) -> usize {
    let mut i = start + 1;
    while i < lines.len() {
        let trimmed = lines[i].trim();
        if !trimmed.is_empty() && indent_of(lines[i]) <= block_indent {
            return i; // Back to the level of the block start
        }
        i += 1;
    }
    i
}

/// Coerce string literals to `.to_string()` when the return type is String.
fn maybe_to_string(expr: &str, ret_type: &str) -> String {
    if ret_type.contains("String") {
        let re_str_lit = Regex::new(r#"^"[^"]*"$"#).unwrap();
        if re_str_lit.is_match(expr) {
            return format!("{}.to_string()", expr);
        }
    }
    expr.to_string()
}

/// Check if the output lines contain a terminal return statement.
fn has_terminal_return(lines: &[String]) -> bool {
    lines
        .iter()
        .rev()
        .take(5)
        .any(|l| {
            let t = l.trim();
            t.starts_with("return ") || t == "return;" || t.contains("todo!(")
        })
}

/// Check if a Python function is suitable for transpilation.
///
/// Rejects functions with complex framework dependencies, generators, lambdas, etc.
pub fn is_transpilable(func: &FunctionRecord) -> bool {
    let code = &func.code;

    // Skip test functions
    if func.name.starts_with("test_") {
        return false;
    }
    // Skip dunder methods
    if func.name.starts_with("__") && func.name.ends_with("__") {
        return false;
    }
    // Skip async functions (for now)
    if func.is_async {
        return false;
    }
    // Skip very large functions
    if func.size_lines > 50 {
        return false;
    }

    // Reject patterns that don't transpile well
    let reject_patterns = [
        "lambda ", "yield ", "yield\n", "async for", "async with",
        "subprocess", "os.path", "open(", "import ",
        "tkinter", "flask", "django", "fastapi", "streamlit",
        "torch", "tensorflow", "numpy", "pandas",
        "@property", "@staticmethod", "@classmethod",
        "super()", "cls(",
    ];

    for pattern in &reject_patterns {
        if code.contains(pattern) {
            return false;
        }
    }

    // Reject comprehensions (complex to transpile)
    if code.contains(" for ") && code.contains(" in ") && code.contains("]") {
        // Likely a list comprehension
        let re_comp = Regex::new(r"\[.+\bfor\b.+\bin\b.+\]").unwrap();
        if re_comp.is_match(code) {
            return false;
        }
    }

    true
}

/// Transpile a module (multiple functions) into a complete Rust source file.
pub fn transpile_module(functions: &[FunctionRecord]) -> String {
    let mut lines = Vec::new();

    lines.push("// Auto-transpiled by X-Ray Rustify Pipeline".to_string());
    lines.push("use std::collections::{HashMap, HashSet};".to_string());
    lines.push(String::new());

    for func in functions {
        if !is_transpilable(func) {
            lines.push(format!("// Skipped: {} (not transpilable)", func.name));
            lines.push(String::new());
            continue;
        }

        lines.push(format!(
            "/// Transpiled from {}:{}",
            func.file_path, func.line_start
        ));
        lines.push(transpile_function(func));
        lines.push(String::new());
    }

    lines.join("\n")
}
