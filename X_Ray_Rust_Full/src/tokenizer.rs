// src/tokenizer.rs — Text tokenization & similarity primitives
use regex::Regex;
use std::collections::{HashMap, HashSet};
use std::sync::LazyLock;
use crate::config;

static SPLIT_RE: LazyLock<Regex> = LazyLock::new(|| {
    // Rust regex doesn't support look-ahead, so we use a simpler pattern
    // that splits on lowercase runs, uppercase-then-lowercase runs, uppercase runs, digits
    Regex::new(r"[a-z]+|[A-Z][a-z]*|[0-9]+").unwrap()
});

/// Tokenize text: split on non-alphanum, split camelCase, lowercase, filter stop words
pub fn tokenize(text: &str) -> Vec<String> {
    let stops = config::stop_words();
    let cleaned = text.chars().map(|c| {
        if c.is_alphanumeric() || c == '_' { c } else { ' ' }
    }).collect::<String>();

    let mut tokens = Vec::new();
    for word in cleaned.split_whitespace() {
        for m in SPLIT_RE.find_iter(word) {
            let tok = m.as_str().to_lowercase();
            if tok.len() > 1 && !stops.contains(tok.as_str()) {
                tokens.push(tok);
            }
        }
    }
    tokens
}

/// Term frequency counter
pub fn term_freq(tokens: &[String]) -> HashMap<String, u32> {
    let mut freq = HashMap::new();
    for t in tokens {
        *freq.entry(t.clone()).or_insert(0) += 1;
    }
    freq
}

/// Cosine similarity between two term-frequency maps
pub fn cosine_similarity(a: &HashMap<String, u32>, b: &HashMap<String, u32>) -> f64 {
    if a.is_empty() || b.is_empty() {
        return 0.0;
    }
    let dot: f64 = a.iter()
        .filter_map(|(k, va)| b.get(k).map(|vb| (*va as f64) * (*vb as f64)))
        .sum();
    let norm_a: f64 = a.values().map(|v| (*v as f64).powi(2)).sum::<f64>().sqrt();
    let norm_b: f64 = b.values().map(|v| (*v as f64).powi(2)).sum::<f64>().sqrt();
    let denom = norm_a * norm_b;
    if denom == 0.0 { 0.0 } else { (dot / denom).min(1.0) }
}

/// Jaccard similarity between two sets
pub fn jaccard(a: &HashSet<String>, b: &HashSet<String>) -> f64 {
    if a.is_empty() && b.is_empty() {
        return 0.0;
    }
    let inter = a.intersection(b).count() as f64;
    let union = a.union(b).count() as f64;
    if union == 0.0 { 0.0 } else { inter / union }
}
