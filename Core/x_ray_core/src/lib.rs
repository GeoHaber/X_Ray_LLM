//! # x_ray_core — Rust acceleration for X_Ray duplicate detection
//!
//! Ports the CPU-hot-path of X_Ray's duplicate-detection pipeline to Rust,
//! giving 10–50× single-threaded speedup and true multi-core parallelism
//! (Python's GIL is released during batch operations).
//!
//! ## Ported functions
//!
//! | Python function              | Rust equivalent              |
//! |------------------------------|------------------------------|
//! | `_normalized_token_stream`   | `normalized_token_stream`    |
//! | `_ngram_fingerprints`        | `ngram_fingerprints`         |
//! | `_token_ngram_similarity`    | `token_ngram_similarity`     |
//! | `_ast_node_histogram`        | `ast_node_histogram`         |
//! | `_ast_histogram_similarity`  | `ast_histogram_similarity`   |
//! | `code_similarity`            | `code_similarity`            |
//! | `cosine_similarity`          | `cosine_similarity_map`      |
//! | *(new)* batch API            | `batch_code_similarity`      |
//! | `normalize_code`             | `normalize_code`             |

use pyo3::prelude::*;
use pyo3::types::PyDict;
use rayon::prelude::*;
use rustc_hash::{FxHashMap, FxHashSet};
use std::hash::{Hash, Hasher};
use std::sync::OnceLock;

// ============================================================
//  Global State — Python builtins (initialised at module load)
// ============================================================

static PYTHON_BUILTINS: OnceLock<FxHashSet<String>> = OnceLock::new();

fn is_builtin(name: &str) -> bool {
    PYTHON_BUILTINS
        .get()
        .map_or(false, |s| s.contains(name))
}

// ============================================================
//  Python Keyword / Soft-keyword Sets
// ============================================================

/// Python 3.13 hard keywords.
const KEYWORDS: &[&str] = &[
    "False", "None", "True", "and", "as", "assert", "async", "await",
    "break", "class", "continue", "def", "del", "elif", "else", "except",
    "finally", "for", "from", "global", "if", "import", "in", "is",
    "lambda", "nonlocal", "not", "or", "pass", "raise", "return", "try",
    "while", "with", "yield",
];

/// Python 3.12+ soft keywords.
const SOFT_KEYWORDS: &[&str] = &["match", "case", "type", "_"];

fn is_keyword(s: &str) -> bool {
    KEYWORDS.iter().any(|&kw| kw == s)
}

fn is_soft_keyword(s: &str) -> bool {
    SOFT_KEYWORDS.iter().any(|&kw| kw == s)
}

// ============================================================
//  String-prefix check   (r, b, f, u, rb, br, rf, fr, …)
// ============================================================

fn is_string_prefix(s: &str) -> bool {
    matches!(
        s.to_ascii_lowercase().as_str(),
        "r" | "u" | "b" | "f" | "rb" | "br" | "rf" | "fr"
    )
}

// ============================================================
//  Python Tokenizer  (handles strings, comments, numbers,
//                      identifiers, operators, delimiters)
// ============================================================

/// Raw token produced by the tokenizer before normalisation.
#[derive(Debug, Clone)]
enum RawToken {
    Name(String),
    Number,
    StringLit,
    Op(String),
    Delim(String),
}

struct PyTokenizer<'a> {
    src: &'a [u8],
    pos: usize,
}

impl<'a> PyTokenizer<'a> {
    fn new(src: &'a str) -> Self {
        // Strip UTF-8 BOM if present.
        let bytes = src.as_bytes();
        let start = if bytes.starts_with(&[0xEF, 0xBB, 0xBF]) { 3 } else { 0 };
        Self { src: bytes, pos: start }
    }

    // ---- helpers ---------------------------------------------------

    #[allow(dead_code)]
    fn peek(&self) -> Option<u8> {
        self.src.get(self.pos).copied()
    }

    fn remaining(&self) -> usize {
        self.src.len() - self.pos
    }

    fn skip_whitespace_and_newlines(&mut self) {
        while self.pos < self.src.len() {
            match self.src[self.pos] {
                b' ' | b'\t' | b'\r' | b'\n' => self.pos += 1,
                b'\\' if self.pos + 1 < self.src.len()
                    && self.src[self.pos + 1] == b'\n' =>
                {
                    self.pos += 2; // line continuation
                }
                _ => break,
            }
        }
    }

    // ---- string reading --------------------------------------------

    fn read_string(&mut self, tokens: &mut Vec<RawToken>) {
        let quote = self.src[self.pos];
        self.pos += 1;

        // Triple-quoted?
        let triple = self.pos + 1 < self.src.len()
            && self.src[self.pos] == quote
            && self.src[self.pos + 1] == quote;

        if triple {
            self.pos += 2;
            loop {
                if self.pos >= self.src.len() { break; }
                if self.src[self.pos] == b'\\' {
                    self.pos += 2.min(self.remaining());
                } else if self.pos + 2 < self.src.len()
                    && self.src[self.pos] == quote
                    && self.src[self.pos + 1] == quote
                    && self.src[self.pos + 2] == quote
                {
                    self.pos += 3;
                    break;
                } else {
                    self.pos += 1;
                }
            }
        } else {
            loop {
                if self.pos >= self.src.len() { break; }
                let ch = self.src[self.pos];
                if ch == b'\\' {
                    self.pos += 2.min(self.remaining());
                } else if ch == quote {
                    self.pos += 1;
                    break;
                } else if ch == b'\n' {
                    break; // unterminated
                } else {
                    self.pos += 1;
                }
            }
        }
        tokens.push(RawToken::StringLit);
    }

    // ---- number reading --------------------------------------------

    fn read_digits(&mut self) {
        while self.pos < self.src.len() {
            let ch = self.src[self.pos];
            if ch.is_ascii_digit() || ch == b'_' { self.pos += 1; } else { break; }
        }
    }

    fn read_hex(&mut self) {
        while self.pos < self.src.len() {
            let ch = self.src[self.pos];
            if ch.is_ascii_hexdigit() || ch == b'_' { self.pos += 1; } else { break; }
        }
    }

    fn read_oct(&mut self) {
        while self.pos < self.src.len() {
            let ch = self.src[self.pos];
            if (ch >= b'0' && ch <= b'7') || ch == b'_' { self.pos += 1; } else { break; }
        }
    }

    fn read_bin(&mut self) {
        while self.pos < self.src.len() {
            let ch = self.src[self.pos];
            if ch == b'0' || ch == b'1' || ch == b'_' { self.pos += 1; } else { break; }
        }
    }

    fn read_decimal(&mut self) {
        self.read_digits();
        if self.pos < self.src.len() && self.src[self.pos] == b'.' {
            self.pos += 1;
            self.read_digits();
        }
        if self.pos < self.src.len()
            && (self.src[self.pos] == b'e' || self.src[self.pos] == b'E')
        {
            self.pos += 1;
            if self.pos < self.src.len()
                && (self.src[self.pos] == b'+' || self.src[self.pos] == b'-')
            {
                self.pos += 1;
            }
            self.read_digits();
        }
    }

    fn read_number(&mut self, tokens: &mut Vec<RawToken>) {
        if self.src[self.pos] == b'0' && self.pos + 1 < self.src.len() {
            match self.src[self.pos + 1] {
                b'x' | b'X' => { self.pos += 2; self.read_hex(); }
                b'o' | b'O' => { self.pos += 2; self.read_oct(); }
                b'b' | b'B' => { self.pos += 2; self.read_bin(); }
                _ => self.read_decimal(),
            }
        } else {
            self.read_decimal();
        }
        // complex suffix
        if self.pos < self.src.len()
            && (self.src[self.pos] == b'j' || self.src[self.pos] == b'J')
        {
            self.pos += 1;
        }
        tokens.push(RawToken::Number);
    }

    // ---- identifier / keyword reading ------------------------------

    fn read_name(&mut self, tokens: &mut Vec<RawToken>) {
        let start = self.pos;
        while self.pos < self.src.len() {
            let ch = self.src[self.pos];
            if ch.is_ascii_alphanumeric() || ch == b'_' {
                self.pos += 1;
            } else {
                break;
            }
        }
        let name = std::str::from_utf8(&self.src[start..self.pos]).unwrap_or("");

        // String prefix? (e.g., f"…", rb"…")
        if self.pos < self.src.len()
            && (self.src[self.pos] == b'\'' || self.src[self.pos] == b'"')
            && is_string_prefix(name)
        {
            self.read_string(tokens);
            return;
        }

        tokens.push(RawToken::Name(name.to_string()));
    }

    // ---- operator / delimiter reading ------------------------------

    fn read_operator(&mut self, tokens: &mut Vec<RawToken>) {
        let start = self.pos;
        let ch = self.src[self.pos];
        self.pos += 1;

        // Multi-character operators
        if self.pos < self.src.len() {
            let next = self.src[self.pos];
            match (ch, next) {
                // 3-char operators: **=  //=  <<=  >>=
                (b'*', b'*') | (b'/', b'/') | (b'<', b'<') | (b'>', b'>')
                    if self.pos + 1 < self.src.len()
                        && self.src[self.pos + 1] == b'=' =>
                {
                    self.pos += 2;
                }
                // Ellipsis: ...
                (b'.', b'.') if self.pos + 1 < self.src.len()
                    && self.src[self.pos + 1] == b'.' =>
                {
                    self.pos += 2;
                }
                // 2-char compound assignment
                (b'+', b'=') | (b'-', b'=') | (b'*', b'=') | (b'/', b'=')
                | (b'%', b'=') | (b'|', b'=') | (b'^', b'=') | (b'&', b'=')
                | (b'@', b'=') => { self.pos += 1; }
                // 2-char comparison / walrus
                (b'=', b'=') | (b'!', b'=') | (b'<', b'=') | (b'>', b'=')
                | (b':', b'=') => { self.pos += 1; }
                // 2-char arithmetic / bitwise
                (b'*', b'*') | (b'/', b'/') | (b'<', b'<') | (b'>', b'>') => {
                    self.pos += 1;
                }
                // Arrow
                (b'-', b'>') => { self.pos += 1; }
                _ => {} // single-character
            }
        }

        let text = std::str::from_utf8(&self.src[start..self.pos]).unwrap_or("");

        if text.len() == 1 && b"()[]{},:;".contains(&ch) {
            tokens.push(RawToken::Delim(text.to_string()));
        } else if text == "." {
            tokens.push(RawToken::Delim(text.to_string()));
        } else {
            tokens.push(RawToken::Op(text.to_string()));
        }
    }

    // ---- main tokenise loop ----------------------------------------

    fn tokenize(&mut self) -> Vec<RawToken> {
        let mut tokens = Vec::with_capacity(256);

        while self.pos < self.src.len() {
            self.skip_whitespace_and_newlines();
            if self.pos >= self.src.len() { break; }

            let ch = self.src[self.pos];

            match ch {
                // Comment — skip to end of line
                b'#' => {
                    while self.pos < self.src.len() && self.src[self.pos] != b'\n' {
                        self.pos += 1;
                    }
                }
                // String literal
                b'\'' | b'"' => self.read_string(&mut tokens),
                // Number
                b'0'..=b'9' => self.read_number(&mut tokens),
                // Float starting with dot  (.5)
                b'.' if self.pos + 1 < self.src.len()
                    && self.src[self.pos + 1].is_ascii_digit() =>
                {
                    self.read_number(&mut tokens);
                }
                // Identifier / keyword / string prefix
                b'a'..=b'z' | b'A'..=b'Z' | b'_' => self.read_name(&mut tokens),
                // Operator or delimiter
                _ => self.read_operator(&mut tokens),
            }
        }

        tokens
    }
}

// ============================================================
//  Normalised Token Stream
// ============================================================

/// Produce a normalised token stream from Python source code.
///
/// - Keywords → kept as-is
/// - Builtins → kept as-is
/// - Other identifiers → `"ID"`
/// - Numbers → `"NUM"`
/// - Strings → `"STR"`
/// - Operators / delimiters → kept as-is
fn normalized_token_stream_impl(code: &str) -> Vec<String> {
    let mut tok = PyTokenizer::new(code);
    let raw = tok.tokenize();

    raw.into_iter()
        .map(|t| match t {
            RawToken::Name(name) => {
                if is_keyword(&name) || is_soft_keyword(&name) {
                    name
                } else if is_builtin(&name) {
                    name
                } else {
                    "ID".to_string()
                }
            }
            RawToken::Number => "NUM".to_string(),
            RawToken::StringLit => "STR".to_string(),
            RawToken::Op(s) | RawToken::Delim(s) => s,
        })
        .collect()
}

// ============================================================
//  Fast Hashing  (FxHash — ~60× faster than MD5)
// ============================================================

fn fx_hash_str(s: &str) -> u64 {
    let mut h = rustc_hash::FxHasher::default();
    s.hash(&mut h);
    h.finish()
}

// ============================================================
//  Winnowed N-gram Fingerprinting  (MOSS / Schleimer 2003)
// ============================================================

/// Hash every contiguous n-gram, then keep the minimum hash in
/// each sliding window of size `w`.
fn ngram_fingerprints_impl(tokens: &[String], n: usize, w: usize) -> FxHashSet<u64> {
    if tokens.len() < n {
        return FxHashSet::default();
    }

    // 1. Hash each n-gram
    let num_grams = tokens.len() - n + 1;
    let mut hashes = Vec::with_capacity(num_grams);
    for i in 0..num_grams {
        // Join tokens with space separator (matches Python behaviour)
        let mut gram = String::with_capacity(n * 6);
        for j in 0..n {
            if j > 0 { gram.push(' '); }
            gram.push_str(&tokens[i + j]);
        }
        hashes.push(fx_hash_str(&gram));
    }

    // 2. Winnowing: select minimum hash in each window
    if hashes.len() < w {
        return hashes.into_iter().collect();
    }

    let mut fps = FxHashSet::with_capacity_and_hasher(hashes.len() / 2, Default::default());
    for i in 0..=(hashes.len() - w) {
        let min_h = hashes[i..i + w].iter().copied().min().unwrap();
        fps.insert(min_h);
    }
    fps
}

// ============================================================
//  AST Node Histogram Estimation (from token stream)
// ============================================================

/// Counts approximate Python AST node types from the raw token stream.
///
/// This is not a real parser, but it counts statement-level keywords
/// (if, for, while, def, …) and expression-level patterns (call, subscript,
/// attribute, binary-op, …) to produce a histogram that tracks relative
/// code structure.  Two pieces of code with the same structure produce
/// similar histograms; cosine similarity then measures the overlap.
fn ast_histogram_from_tokens(raw_tokens: &[RawToken]) -> FxHashMap<String, u32> {
    let mut h: FxHashMap<String, u32> = FxHashMap::default();

    macro_rules! inc {
        ($key:expr) => {{
            *h.entry($key.to_string()).or_insert(0) += 1;
        }};
    }

    inc!("Module");

    for (i, tok) in raw_tokens.iter().enumerate() {
        match tok {
            RawToken::Name(name) => {
                let s = name.as_str();

                // Every non-keyword identifier counts as Name
                if !is_keyword(s) && !is_soft_keyword(s) {
                    inc!("Name");
                }

                match s {
                    "def" => { inc!("FunctionDef"); inc!("arguments"); }
                    "class" => inc!("ClassDef"),
                    "if" | "elif" => inc!("If"),
                    "for" => inc!("For"),
                    "while" => inc!("While"),
                    "try" => inc!("Try"),
                    "except" => inc!("ExceptHandler"),
                    "with" => inc!("With"),
                    "return" => inc!("Return"),
                    "yield" => inc!("Yield"),
                    "raise" => inc!("Raise"),
                    "import" => inc!("Import"),
                    "from" => {
                        // from…import → ImportFrom
                        let rest = &raw_tokens[i..];
                        if rest.iter().any(|t| matches!(t, RawToken::Name(n) if n == "import")) {
                            inc!("ImportFrom");
                        }
                    }
                    "assert" => inc!("Assert"),
                    "pass" => inc!("Pass"),
                    "break" => inc!("Break"),
                    "continue" => inc!("Continue"),
                    "del" => inc!("Delete"),
                    "global" => inc!("Global"),
                    "nonlocal" => inc!("Nonlocal"),
                    "lambda" => inc!("Lambda"),
                    "and" | "or" => inc!("BoolOp"),
                    "not" => { inc!("UnaryOp"); inc!("Not"); }
                    "True" | "False" | "None" => inc!("Constant"),
                    "is" => inc!("Compare"),
                    "in" => {
                        // Skip when part of `for … in` — only count standalone
                        let prev_is_for = i > 0
                            && matches!(&raw_tokens[i - 1], RawToken::Name(p) if p == "for");
                        let prev_is_not = i > 0
                            && matches!(&raw_tokens[i - 1], RawToken::Name(p) if p == "not");
                        if !prev_is_for {
                            inc!("Compare");
                            if prev_is_not { inc!("NotIn"); }
                        }
                    }
                    "await" => inc!("Await"),
                    _ => {
                        // Check for call:  name(
                        if let Some(RawToken::Delim(d)) = raw_tokens.get(i + 1) {
                            if d == "(" { inc!("Call"); }
                            if d == "[" { inc!("Subscript"); }
                        }
                        // Check for attribute:  .name
                        if i > 0 {
                            if let Some(RawToken::Delim(d)) = raw_tokens.get(i - 1) {
                                if d == "." { inc!("Attribute"); }
                            }
                        }
                    }
                }
            }
            RawToken::Number => inc!("Constant"),
            RawToken::StringLit => inc!("Constant"),
            RawToken::Op(op) => {
                match op.as_str() {
                    "+" | "-" | "*" | "/" | "//" | "%" | "**" | "@"
                    | "<<" | ">>" | "|" | "^" | "&" => { inc!("BinOp"); }
                    "~" => { inc!("UnaryOp"); }
                    "==" | "!=" | "<" | ">" | "<=" | ">=" => { inc!("Compare"); }
                    "=" => { inc!("Assign"); }
                    "+=" | "-=" | "*=" | "/=" | "//=" | "%=" | "**="
                    | "<<=" | ">>=" | "|=" | "^=" | "&=" | "@=" => { inc!("AugAssign"); }
                    ":=" => { inc!("NamedExpr"); }
                    "..." => { inc!("Constant"); } // Ellipsis
                    _ => {}
                }
            }
            RawToken::Delim(d) => {
                match d.as_str() {
                    "{" => { inc!("Dict"); } // approximate
                    _ => {}
                }
            }
        }
    }
    h
}

/// Build an AST histogram from source code.
fn ast_histogram_impl(code: &str) -> FxHashMap<String, u32> {
    let mut tok = PyTokenizer::new(code);
    let raw = tok.tokenize();
    ast_histogram_from_tokens(&raw)
}

// ============================================================
//  Similarity Functions
// ============================================================

/// Cosine similarity between two term-frequency maps.
fn cosine_sim(a: &FxHashMap<String, u32>, b: &FxHashMap<String, u32>) -> f64 {
    if a.is_empty() || b.is_empty() {
        return 0.0;
    }
    let mut dot: f64 = 0.0;
    let mut mag_a: f64 = 0.0;
    let mut mag_b: f64 = 0.0;

    for (k, &va) in a.iter() {
        let va = va as f64;
        mag_a += va * va;
        if let Some(&vb) = b.get(k) {
            dot += va * vb as f64;
        }
    }
    for (_, &vb) in b.iter() {
        let vb = vb as f64;
        mag_b += vb * vb;
    }

    if mag_a == 0.0 || mag_b == 0.0 {
        return 0.0;
    }
    let result = dot / (mag_a.sqrt() * mag_b.sqrt());
    result.min(1.0) // clamp float rounding
}

/// Jaccard similarity between two fingerprint sets.
fn jaccard_sim(a: &FxHashSet<u64>, b: &FxHashSet<u64>) -> f64 {
    if a.is_empty() || b.is_empty() {
        return 0.0;
    }
    let intersection = a.iter().filter(|x| b.contains(x)).count();
    let union = a.len() + b.len() - intersection;
    if union == 0 { 0.0 } else { intersection as f64 / union as f64 }
}

// ============================================================
//  Combined code_similarity  (0.35 × tok_ngram + 0.65 × ast_hist)
// ============================================================

/// Pre-computed data for one code block (avoids re-parsing in batch mode).
struct Preprocessed {
    fingerprints: FxHashSet<u64>,
    histogram: FxHashMap<String, u32>,
}

fn preprocess(code: &str) -> Preprocessed {
    let tokens = normalized_token_stream_impl(code);
    let fingerprints = ngram_fingerprints_impl(&tokens, 5, 4);
    let histogram = ast_histogram_impl(code);
    Preprocessed { fingerprints, histogram }
}

fn similarity_from_preprocessed(a: &Preprocessed, b: &Preprocessed) -> f64 {
    let tok_sim = jaccard_sim(&a.fingerprints, &b.fingerprints);
    let ast_sim = cosine_sim(&a.histogram, &b.histogram);
    (0.35 * tok_sim + 0.65 * ast_sim).min(1.0)
}

fn code_similarity_impl(code_a: &str, code_b: &str) -> f64 {
    if code_a.is_empty() || code_b.is_empty() {
        return 0.0;
    }
    if code_a == code_b {
        return 1.0;
    }
    let a = preprocess(code_a);
    let b = preprocess(code_b);
    similarity_from_preprocessed(&a, &b)
}

// ============================================================
//  Batch Pairwise Similarity  (releases the GIL, uses rayon)
// ============================================================

/// Compute full N×N pairwise similarity matrix in parallel.
///
/// Returns a flat `Vec<Vec<f64>>` representing the upper-triangular
/// similarity matrix (symmetric, diagonal = 1.0).
fn batch_code_similarity_impl(codes: &[String]) -> Vec<Vec<f64>> {
    let n = codes.len();

    // Phase 1: pre-compute fingerprints + histograms (parallel)
    let preprocessed: Vec<Preprocessed> = codes
        .par_iter()
        .map(|c| preprocess(c))
        .collect();

    // Phase 2: compute all unique pairs (parallel)
    let pairs: Vec<(usize, usize)> = (0..n)
        .flat_map(|i| ((i + 1)..n).map(move |j| (i, j)))
        .collect();

    let sims: Vec<(usize, usize, f64)> = pairs
        .par_iter()
        .map(|&(i, j)| {
            let sim = similarity_from_preprocessed(&preprocessed[i], &preprocessed[j]);
            (i, j, sim)
        })
        .collect();

    // Build symmetric matrix
    let mut matrix = vec![vec![0.0f64; n]; n];
    for i in 0..n {
        matrix[i][i] = 1.0;
    }
    for (i, j, sim) in sims {
        matrix[i][j] = sim;
        matrix[j][i] = sim;
    }
    matrix
}

// ============================================================
//  normalize_code  (regex: strip docstrings + comments + blanks)
// ============================================================

fn normalize_code_impl(code: &str) -> String {
    use std::sync::LazyLock;

    static RE_DOC: LazyLock<regex::Regex> = LazyLock::new(|| {
        regex::Regex::new(r#"(?ms)"""[\s\S]*?"""|'''[\s\S]*?'''"#).expect("Invalid RE_DOC regex")
    });
    static RE_COMMENT: LazyLock<regex::Regex> = LazyLock::new(|| {
        regex::Regex::new(r"#[^\n]*").expect("Invalid RE_COMMENT regex")
    });
    static RE_TRAILING: LazyLock<regex::Regex> = LazyLock::new(|| {
        regex::Regex::new(r"[ \t]+\n").expect("Invalid RE_TRAILING regex")
    });
    static RE_BLANK: LazyLock<regex::Regex> = LazyLock::new(|| {
        regex::Regex::new(r"\n{3,}").expect("Invalid RE_BLANK regex")
    });

    let s = RE_DOC.replace_all(code, "");
    let s = RE_COMMENT.replace_all(&s, "");
    let s = RE_TRAILING.replace_all(&s, "\n");
    let s = RE_BLANK.replace_all(&s, "\n\n");
    s.trim().to_string()
}

// ============================================================
//  PyO3 Bindings
// ============================================================

/// Normalised token stream — mirrors Python's `_normalized_token_stream`.
#[pyfunction]
fn normalized_token_stream(code: &str) -> PyResult<Vec<String>> {
    Ok(normalized_token_stream_impl(code))
}

/// Winnowed n-gram fingerprints — mirrors Python's `_ngram_fingerprints`.
///
/// Returns a `set[int]` on the Python side.
#[pyfunction]
#[pyo3(signature = (tokens, n=5, w=4))]
fn ngram_fingerprints(tokens: Vec<String>, n: usize, w: usize) -> PyResult<FxHashSet<u64>> {
    if w == 0 {
        return Err(pyo3::exceptions::PyValueError::new_err("Window size w must be > 0"));
    }
    Ok(ngram_fingerprints_impl(&tokens, n, w))
}

/// Token n-gram Jaccard similarity.
#[pyfunction]
fn token_ngram_similarity(code_a: &str, code_b: &str) -> PyResult<f64> {
    let ta = normalized_token_stream_impl(code_a);
    let tb = normalized_token_stream_impl(code_b);
    let fa = ngram_fingerprints_impl(&ta, 5, 4);
    let fb = ngram_fingerprints_impl(&tb, 5, 4);
    Ok(jaccard_sim(&fa, &fb))
}

/// AST node-type histogram — mirrors Python's `_ast_node_histogram`.
///
/// Returns a `dict[str, int]` on the Python side.
#[pyfunction]
fn ast_node_histogram(py: Python<'_>, code: &str) -> PyResult<Py<PyDict>> {
    let h = ast_histogram_impl(code);
    let dict = PyDict::new(py);
    for (k, v) in h {
        dict.set_item(&k, v)?;
    }
    Ok(dict.unbind())
}

/// AST histogram cosine similarity.
#[pyfunction]
fn ast_histogram_similarity(code_a: &str, code_b: &str) -> PyResult<f64> {
    let ha = ast_histogram_impl(code_a);
    let hb = ast_histogram_impl(code_b);
    Ok(cosine_sim(&ha, &hb))
}

/// Generic cosine similarity between two `dict[str, int]` maps.
#[pyfunction]
fn cosine_similarity_map(a: FxHashMap<String, u32>, b: FxHashMap<String, u32>) -> PyResult<f64> {
    Ok(cosine_sim(&a, &b))
}

/// Combined structural code similarity (0.35 × tok + 0.65 × ast).
#[pyfunction]
fn code_similarity(code_a: &str, code_b: &str) -> PyResult<f64> {
    Ok(code_similarity_impl(code_a, code_b))
}

/// Batch pairwise similarity — **releases the GIL** and uses all CPU cores.
///
/// Accepts a list of code strings, returns an N×N similarity matrix.
#[pyfunction]
fn batch_code_similarity(py: Python<'_>, codes: Vec<String>) -> PyResult<Vec<Vec<f64>>> {
    let matrix = py.allow_threads(|| batch_code_similarity_impl(&codes));
    Ok(matrix)
}

/// Strip docstrings, comments, trailing whitespace, and blank lines.
#[pyfunction]
fn normalize_code(code: &str) -> PyResult<String> {
    Ok(normalize_code_impl(code))
}

// ============================================================
//  Module registration
// ============================================================

/// x_ray_core — Rust acceleration for X_Ray duplicate detection.
#[pymodule]
fn x_ray_core(py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Initialise the builtins set from the running Python interpreter —
    // guarantees exact parity with `frozenset(dir(builtins))`.
    let builtins_mod = py.import("builtins")?;
    let names_obj = builtins_mod.call_method1("dir", (builtins_mod.as_ref(),))
        .or_else(|_| -> PyResult<_> {
            // Fallback: evaluate dir(__builtins__) directly
            py.eval(c"sorted(dir(__builtins__))", None, None)
        })?;
    let names: Vec<String> = names_obj.extract()?;
    PYTHON_BUILTINS.get_or_init(|| names.into_iter().collect());

    m.add_function(wrap_pyfunction!(normalized_token_stream, m)?)?;
    m.add_function(wrap_pyfunction!(ngram_fingerprints, m)?)?;
    m.add_function(wrap_pyfunction!(token_ngram_similarity, m)?)?;
    m.add_function(wrap_pyfunction!(ast_node_histogram, m)?)?;
    m.add_function(wrap_pyfunction!(ast_histogram_similarity, m)?)?;
    m.add_function(wrap_pyfunction!(cosine_similarity_map, m)?)?;
    m.add_function(wrap_pyfunction!(code_similarity, m)?)?;
    m.add_function(wrap_pyfunction!(batch_code_similarity, m)?)?;
    m.add_function(wrap_pyfunction!(normalize_code, m)?)?;

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_tokenizer_simple() {
        let code = "def foo(x): return x + 1";
        let tokens = normalized_token_stream_impl(code);
        assert_eq!(tokens, vec![
            "def", "ID", "(", "ID", ")", ":", 
            "return", "ID", "+", "NUM"
        ]);
    }

    #[test]
    fn test_tokenizer_strings() {
        let code = "s = \"hello\"";
        let tokens = normalized_token_stream_impl(code);
        assert_eq!(tokens, vec!["ID", "=", "STR"]);
    }

    #[test]
    fn test_tokenizer_comments() {
        let code = "x = 1 # comment\ny = 2";
        let tokens = normalized_token_stream_impl(code);
        assert_eq!(tokens, vec!["ID", "=", "NUM", "ID", "=", "NUM"]);
    }

    #[test]
    fn test_ngram_fingerprints_safety() {
        let tokens = vec!["a".to_string(), "b".to_string(), "c".to_string()];
        // w=0 should be handled safely if exposed via impl (though impl takes usize)
        // logic test:
        let fps = ngram_fingerprints_impl(&tokens, 2, 2);
        assert!(!fps.is_empty());
    }
}
