// src/duplicates.rs — Duplicate/similar function detection (unified, zero duplication)
//
// 3-stage pipeline: exact hash → structural hash → near-duplicate (similarity) → semantic
// Uses UnionFind for clustering.

use crate::similarity;
use crate::types::{DuplicateGroup, FunctionRecord};
use std::collections::{HashMap, HashSet};

// ── Constants ──────────────────────────────────────────────────────

const NEAR_DUP_THRESHOLD: f64 = 0.80;
const TOKEN_PREFILTER: f64 = 0.25;
const SIZE_RATIO_MIN: f64 = 0.35;
const SEMANTIC_THRESHOLD: f64 = 0.50;
const SEMANTIC_MIN_LINES: u32 = 8;

/// Boilerplate methods to skip
fn is_boilerplate(name: &str) -> bool {
    matches!(
        name,
        "__init__" | "__repr__" | "__str__" | "__eq__" | "__hash__"
            | "__len__" | "__iter__" | "__next__" | "__enter__" | "__exit__"
            | "__getitem__" | "__setitem__" | "__contains__"
            | "setUp" | "tearDown" | "setUpClass" | "tearDownClass"
    )
}

// ── UnionFind ──────────────────────────────────────────────────────

struct UnionFind {
    parent: HashMap<String, String>,
}

impl UnionFind {
    fn new() -> Self {
        Self { parent: HashMap::new() }
    }

    fn find(&mut self, x: &str) -> String {
        if !self.parent.contains_key(x) {
            self.parent.insert(x.to_string(), x.to_string());
            return x.to_string();
        }
        let mut root = x.to_string();
        while self.parent[&root] != root {
            let grandparent = self.parent[&self.parent[&root]].clone();
            self.parent.insert(root.clone(), grandparent.clone());
            root = grandparent;
        }
        root
    }

    fn union(&mut self, a: &str, b: &str) {
        let ra = self.find(a);
        let rb = self.find(b);
        if ra != rb {
            self.parent.insert(ra, rb);
        }
    }

    fn groups(&mut self) -> HashMap<String, Vec<String>> {
        let keys: Vec<String> = self.parent.keys().cloned().collect();
        let mut groups: HashMap<String, Vec<String>> = HashMap::new();
        for k in &keys {
            let root = self.find(k);
            groups.entry(root).or_default().push(k.clone());
        }
        groups
    }
}

// ── Main Pipeline ──────────────────────────────────────────────────

/// Find all duplicate/similar function groups
pub fn find_duplicates(functions: &[FunctionRecord]) -> Vec<DuplicateGroup> {
    let mut groups = Vec::new();
    let mut seen_keys: HashSet<String> = HashSet::new();
    let mut group_id: u32 = 0;

    // Index functions by key
    let func_map: HashMap<String, &FunctionRecord> =
        functions.iter().map(|f| (f.key(), f)).collect();

    // Stage 1a: Exact code hash matches
    {
        let mut hash_groups: HashMap<&str, Vec<&FunctionRecord>> = HashMap::new();
        for f in functions {
            hash_groups.entry(&f.code_hash).or_default().push(f);
        }
        for (_hash, funcs) in &hash_groups {
            if funcs.len() < 2 { continue; }
            // Must have functions from different files
            let files: HashSet<&str> = funcs.iter().map(|f| f.file_path.as_str()).collect();
            if files.len() < 2 { continue; }

            let members: Vec<serde_json::Value> = funcs.iter().map(|f| func_to_json(f, 1.0)).collect();
            let keys: Vec<String> = funcs.iter().map(|f| f.key()).collect();
            for k in &keys { seen_keys.insert(k.clone()); }

            groups.push(DuplicateGroup {
                group_id,
                similarity_type: "exact".to_string(),
                avg_similarity: 1.0,
                functions: members,
                merge_suggestion: "These functions are identical. Consolidate into a shared module.".to_string(),
            });
            group_id += 1;
        }
    }

    // Stage 1b: Structural hash matches
    {
        let mut struct_groups: HashMap<&str, Vec<&FunctionRecord>> = HashMap::new();
        for f in functions {
            if seen_keys.contains(&f.key()) { continue; }
            if f.size_lines < 4 { continue; }
            struct_groups.entry(&f.structure_hash).or_default().push(f);
        }
        for (_hash, funcs) in &struct_groups {
            if funcs.len() < 2 { continue; }
            let keys: Vec<String> = funcs.iter().map(|f| f.key()).collect();
            let members: Vec<serde_json::Value> = funcs.iter().map(|f| func_to_json(f, 1.0)).collect();
            for k in &keys { seen_keys.insert(k.clone()); }

            groups.push(DuplicateGroup {
                group_id,
                similarity_type: "structural".to_string(),
                avg_similarity: 1.0,
                functions: members,
                merge_suggestion: "Structurally identical — differ only in variable names. Unify with parameters.".to_string(),
            });
            group_id += 1;
        }
    }

    // Stage 2: Near-duplicates (pairwise similarity)
    {
        let candidates: Vec<&FunctionRecord> = functions
            .iter()
            .filter(|f| !seen_keys.contains(&f.key()) && f.size_lines >= 4)
            .collect();

        let mut uf = UnionFind::new();
        let mut pair_sims: HashMap<(String, String), f64> = HashMap::new();

        for i in 0..candidates.len() {
            for j in (i + 1)..candidates.len() {
                let fa = candidates[i];
                let fb = candidates[j];

                // Size ratio pre-filter
                let size_ratio = fa.size_lines.min(fb.size_lines) as f64
                    / fa.size_lines.max(fb.size_lines) as f64;
                if size_ratio < SIZE_RATIO_MIN { continue; }

                // Token cosine pre-filter
                let token_cos = similarity::quick_token_cosine(&fa.code, &fb.code);
                if token_cos < TOKEN_PREFILTER { continue; }

                // Full code similarity
                let sim = similarity::code_similarity(&fa.code, &fb.code);
                if sim >= NEAR_DUP_THRESHOLD {
                    uf.union(&fa.key(), &fb.key());
                    pair_sims.insert((fa.key(), fb.key()), sim);
                }
            }
        }

        for (_root, members) in uf.groups() {
            if members.len() < 2 { continue; }

            // Calculate average similarity
            let mut total_sim = 0.0;
            let mut count = 0;
            for i in 0..members.len() {
                for j in (i + 1)..members.len() {
                    let key = if members[i] < members[j] {
                        (members[i].clone(), members[j].clone())
                    } else {
                        (members[j].clone(), members[i].clone())
                    };
                    if let Some(&s) = pair_sims.get(&key) {
                        total_sim += s;
                        count += 1;
                    }
                }
            }
            let avg_sim = if count > 0 { total_sim / count as f64 } else { NEAR_DUP_THRESHOLD };

            let funcs: Vec<serde_json::Value> = members
                .iter()
                .filter_map(|k| func_map.get(k))
                .map(|f| func_to_json(f, avg_sim))
                .collect();

            for k in &members { seen_keys.insert(k.clone()); }

            groups.push(DuplicateGroup {
                group_id,
                similarity_type: "near".to_string(),
                avg_similarity: (avg_sim * 100.0).round() / 100.0,
                functions: funcs,
                merge_suggestion: format!("Near-duplicate code ({:.0}% similar). Extract shared logic into a common function.", avg_sim * 100.0),
            });
            group_id += 1;
        }
    }

    // Stage 3: Semantic similarity
    {
        let candidates: Vec<&FunctionRecord> = functions
            .iter()
            .filter(|f| {
                !seen_keys.contains(&f.key())
                    && !is_boilerplate(&f.name)
                    && f.size_lines >= SEMANTIC_MIN_LINES
            })
            .collect();

        let mut uf = UnionFind::new();
        let mut pair_sims: HashMap<(String, String), f64> = HashMap::new();

        for i in 0..candidates.len() {
            for j in (i + 1)..candidates.len() {
                let fa = candidates[i];
                let fb = candidates[j];
                let sim = similarity::semantic_similarity(fa, fb);
                if sim >= SEMANTIC_THRESHOLD {
                    uf.union(&fa.key(), &fb.key());
                    let key = if fa.key() < fb.key() {
                        (fa.key(), fb.key())
                    } else {
                        (fb.key(), fa.key())
                    };
                    pair_sims.insert(key, sim);
                }
            }
        }

        for (_root, members) in uf.groups() {
            if members.len() < 2 { continue; }

            let mut total_sim = 0.0;
            let mut count = 0;
            for i in 0..members.len() {
                for j in (i + 1)..members.len() {
                    let key = if members[i] < members[j] {
                        (members[i].clone(), members[j].clone())
                    } else {
                        (members[j].clone(), members[i].clone())
                    };
                    if let Some(&s) = pair_sims.get(&key) {
                        total_sim += s;
                        count += 1;
                    }
                }
            }
            let avg_sim = if count > 0 { total_sim / count as f64 } else { SEMANTIC_THRESHOLD };

            let funcs: Vec<serde_json::Value> = members
                .iter()
                .filter_map(|k| func_map.get(k))
                .map(|f| func_to_json(f, avg_sim))
                .collect();

            for k in &members { seen_keys.insert(k.clone()); }

            groups.push(DuplicateGroup {
                group_id,
                similarity_type: "semantic".to_string(),
                avg_similarity: (avg_sim * 100.0).round() / 100.0,
                functions: funcs,
                merge_suggestion: format!("Semantically similar ({:.0}%). Consider merging into one parameterized function.", avg_sim * 100.0),
            });
            group_id += 1;
        }
    }

    // Sort groups: exact → structural → near → semantic, then by group_id
    groups.sort_by(|a, b| {
        let type_order = |t: &str| match t {
            "exact" => 0,
            "structural" => 1,
            "near" => 2,
            "semantic" => 3,
            _ => 4,
        };
        type_order(&a.similarity_type)
            .cmp(&type_order(&b.similarity_type))
            .then(b.avg_similarity.partial_cmp(&a.avg_similarity).unwrap_or(std::cmp::Ordering::Equal))
    });

    // Re-number group IDs
    for (i, g) in groups.iter_mut().enumerate() {
        g.group_id = i as u32;
    }

    groups
}

fn func_to_json(f: &FunctionRecord, similarity: f64) -> serde_json::Value {
    serde_json::json!({
        "key": f.key(),
        "name": f.name,
        "file": f.file_path,
        "line": f.line_start,
        "size": f.size_lines,
        "similarity": similarity,
    })
}
