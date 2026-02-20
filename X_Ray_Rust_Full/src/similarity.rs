// src/similarity.rs — Similarity computation engine (unified, zero duplication)
//
// Provides: code_similarity, name_similarity, signature_similarity,
//           callgraph_overlap, semantic_similarity
//
// Uses n-gram fingerprinting (winnowed, MOSS-style) + token histogram.

use crate::tokenizer;
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};
use regex::Regex;
use std::sync::LazyLock;

static RE_PY_TOKEN: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r#"(?x)
        \b(def|class|if|elif|else|for|while|try|except|finally|with|
           return|yield|import|from|as|in|not|and|or|is|lambda|
           raise|pass|break|continue|assert|global|nonlocal|async|await)\b |
        \b(True|False|None|print|len|range|int|str|float|list|dict|set|tuple|
           type|isinstance|hasattr|getattr|setattr|enumerate|zip|map|filter|
           sorted|reversed|any|all|min|max|sum|abs|round|open|super)\b |
        \b[A-Za-z_]\w*\b |
        \b\d+(?:\.\d+)?\b |
        "[^"]*"|'[^']*' |
        [+\-*/=%<>!&|^~@]+|[(){}\[\],;:.]
    "#).unwrap()
});

// Token categories for normalization
fn classify_token(tok: &str) -> Option<String> {
    // Keywords: keep as-is
    let keywords: HashSet<&str> = [
        "def","class","if","elif","else","for","while","try","except",
        "finally","with","return","yield","import","from","as","in","not",
        "and","or","is","lambda","raise","pass","break","continue","assert",
        "global","nonlocal","async","await",
    ].iter().copied().collect();

    let builtins: HashSet<&str> = [
        "True","False","None","print","len","range","int","str","float",
        "list","dict","set","tuple","type","isinstance","hasattr","getattr",
        "setattr","enumerate","zip","map","filter","sorted","reversed","any",
        "all","min","max","sum","abs","round","open","super",
    ].iter().copied().collect();

    if keywords.contains(tok) {
        Some(tok.to_string())
    } else if builtins.contains(tok) {
        Some(tok.to_string())
    } else if tok.chars().next().map_or(false, |c| c.is_alphabetic() || c == '_') {
        Some("ID".to_string())
    } else if tok.chars().next().map_or(false, |c| c.is_ascii_digit()) {
        Some("NUM".to_string())
    } else if tok.starts_with('"') || tok.starts_with('\'') {
        Some("STR".to_string())
    } else {
        Some(tok.to_string()) // operators, punctuation
    }
}

/// Produce normalized token stream from Python source
fn normalized_token_stream(code: &str) -> Vec<String> {
    RE_PY_TOKEN
        .find_iter(code)
        .filter_map(|m| classify_token(m.as_str()))
        .collect()
}

/// Winnowed n-gram fingerprints (MOSS algorithm)
fn ngram_fingerprints(tokens: &[String], n: usize, w: usize) -> HashSet<u64> {
    if tokens.len() < n {
        return HashSet::new();
    }
    // Hash each n-gram
    let hashes: Vec<u64> = (0..=tokens.len() - n)
        .map(|i| {
            let gram = tokens[i..i + n].join(" ");
            let mut hasher = Sha256::new();
            hasher.update(gram.as_bytes());
            let result = hasher.finalize();
            u64::from_be_bytes(result[..8].try_into().unwrap())
        })
        .collect();

    if hashes.len() < w {
        return hashes.into_iter().collect();
    }

    // Winnowing: keep minimum from each window
    let mut fingerprints = HashSet::new();
    for window in hashes.windows(w) {
        if let Some(&min_hash) = window.iter().min() {
            fingerprints.insert(min_hash);
        }
    }
    fingerprints
}

/// Token n-gram similarity (Jaccard of winnowed fingerprints)
fn token_ngram_similarity(code_a: &str, code_b: &str) -> f64 {
    let toks_a = normalized_token_stream(code_a);
    let toks_b = normalized_token_stream(code_b);
    let fp_a = ngram_fingerprints(&toks_a, 5, 4);
    let fp_b = ngram_fingerprints(&toks_b, 5, 4);

    if fp_a.is_empty() && fp_b.is_empty() {
        return 0.0;
    }
    let inter = fp_a.intersection(&fp_b).count() as f64;
    let union = fp_a.union(&fp_b).count() as f64;
    if union == 0.0 { 0.0 } else { inter / union }
}

/// AST node-type histogram similarity
fn ast_histogram(code: &str) -> HashMap<String, u32> {
    let re = Regex::new(r"(?m)^\s*(def|class|if|elif|else|for|while|try|except|finally|with|return|yield|import|from|raise|pass|break|continue|assert|async|await)\b").unwrap();
    let mut counts = HashMap::new();
    for cap in re.captures_iter(code) {
        let kw = cap.get(1).unwrap().as_str();
        *counts.entry(kw.to_string()).or_insert(0) += 1;
    }
    // Also count assignments, calls, and operators
    let re_assign = Regex::new(r"(?m)^\s*\w+\s*=").unwrap();
    *counts.entry("assign".to_string()).or_insert(0) += re_assign.find_iter(code).count() as u32;
    counts
}

fn ast_histogram_similarity(code_a: &str, code_b: &str) -> f64 {
    let hist_a = ast_histogram(code_a);
    let hist_b = ast_histogram(code_b);
    tokenizer::cosine_similarity(&hist_a, &hist_b)
}

/// Combined code similarity (weighted: 35% n-gram + 65% AST histogram)
pub fn code_similarity(code_a: &str, code_b: &str) -> f64 {
    let ngram = token_ngram_similarity(code_a, code_b);
    let ast = ast_histogram_similarity(code_a, code_b);
    (0.35 * ngram + 0.65 * ast).min(1.0)
}

/// Name similarity (Jaccard of tokenized name parts)
pub fn name_similarity(name_a: &str, name_b: &str) -> f64 {
    let toks_a: HashSet<String> = tokenizer::tokenize(name_a).into_iter().collect();
    let toks_b: HashSet<String> = tokenizer::tokenize(name_b).into_iter().collect();
    tokenizer::jaccard(&toks_a, &toks_b)
}

/// Signature similarity (params + return type + async match)
pub fn signature_similarity(
    params_a: &[String], params_b: &[String],
    ret_a: &Option<String>, ret_b: &Option<String>,
    async_a: bool, async_b: bool,
) -> f64 {
    // Jaccard of param name tokens
    let pa: HashSet<String> = params_a.iter().flat_map(|p| tokenizer::tokenize(p)).collect();
    let pb: HashSet<String> = params_b.iter().flat_map(|p| tokenizer::tokenize(p)).collect();
    let param_jaccard = tokenizer::jaccard(&pa, &pb);

    // Param count ratio
    let max_params = params_a.len().max(params_b.len());
    let param_ratio = if max_params == 0 {
        1.0
    } else {
        params_a.len().min(params_b.len()) as f64 / max_params as f64
    };

    // Return type match
    let ret_match = match (ret_a, ret_b) {
        (Some(a), Some(b)) if a == b => 1.0,
        (None, None) => 0.5,
        _ => 0.0,
    };

    // Async match
    let async_match = if async_a == async_b { 1.0 } else { 0.0 };

    (param_jaccard + param_ratio + ret_match + async_match) / 4.0
}

/// Call-graph overlap (Jaccard of calls_to sets)
pub fn callgraph_overlap(calls_a: &[String], calls_b: &[String]) -> f64 {
    let sa: HashSet<String> = calls_a.iter().cloned().collect();
    let sb: HashSet<String> = calls_b.iter().cloned().collect();
    tokenizer::jaccard(&sa, &sb)
}

/// Full semantic similarity (weighted composite)
pub fn semantic_similarity(
    f1: &crate::types::FunctionRecord,
    f2: &crate::types::FunctionRecord,
) -> f64 {
    let name_sim = name_similarity(&f1.name, &f2.name);
    let sig_sim = signature_similarity(
        &f1.parameters, &f2.parameters,
        &f1.return_type, &f2.return_type,
        f1.is_async, f2.is_async,
    );
    let call_sim = callgraph_overlap(&f1.calls_to, &f2.calls_to);

    // Docstring similarity
    let doc_sim = match (&f1.docstring, &f2.docstring) {
        (Some(d1), Some(d2)) => {
            let tf1 = tokenizer::term_freq(&tokenizer::tokenize(d1));
            let tf2 = tokenizer::term_freq(&tokenizer::tokenize(d2));
            tokenizer::cosine_similarity(&tf1, &tf2)
        }
        _ => 0.0,
    };

    0.30 * name_sim + 0.25 * sig_sim + 0.30 * call_sim + 0.15 * doc_sim
}

/// Quick token cosine for pre-filtering
pub fn quick_token_cosine(code_a: &str, code_b: &str) -> f64 {
    let tf_a = tokenizer::term_freq(&tokenizer::tokenize(code_a));
    let tf_b = tokenizer::term_freq(&tokenizer::tokenize(code_b));
    tokenizer::cosine_similarity(&tf_a, &tf_b)
}
