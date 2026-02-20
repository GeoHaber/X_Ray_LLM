// src/smart_graph.rs — Interactive HTML codebase health visualization
//
// Port of Analysis/smart_graph.py
// Builds a node/edge graph of functions colored by health with duplicate links,
// then exports an interactive HTML page using vis-network.js.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::Path;

use crate::types::{DuplicateGroup, FunctionRecord, Severity, SmellIssue};

/// A graph node representing a single function.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GraphNode {
    pub id: String,
    pub label: String,
    pub title: String,
    pub color: String,
    pub health: String,
    pub size: u32,
    pub group: String,
}

/// A graph edge linking duplicate/similar functions.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GraphEdge {
    pub from: String,
    pub to: String,
    pub value: f64,
    pub title: String,
}

/// Build the full graph from scan results.
pub fn build_graph(
    functions: &[FunctionRecord],
    smells: &[SmellIssue],
    duplicates: &[DuplicateGroup],
) -> (Vec<GraphNode>, Vec<GraphEdge>) {
    let smell_map = build_smell_map(smells);

    let nodes: Vec<GraphNode> = functions
        .iter()
        .map(|f| {
            let key = f.key();
            let f_smells = smell_map.get(&key).cloned().unwrap_or_default();
            make_node(f, &f_smells)
        })
        .collect();

    let edges = make_edges(duplicates);

    (nodes, edges)
}

/// Map `file_stem::name` keys to their associated SmellIssue indices.
fn build_smell_map(smells: &[SmellIssue]) -> HashMap<String, Vec<SmellIssue>> {
    let mut map: HashMap<String, Vec<SmellIssue>> = HashMap::new();
    for s in smells {
        if s.name.is_empty() {
            continue;
        }
        let p = Path::new(&s.file_path);
        let parent = p
            .parent()
            .map(|pp| pp.to_string_lossy().replace('\\', "/"))
            .unwrap_or_default();
        let stem = p
            .file_stem()
            .map(|s| s.to_string_lossy().to_string())
            .unwrap_or_default();

        let key = if parent == "." || parent.is_empty() {
            format!("{}::{}", stem, s.name)
        } else {
            format!("{}/{}::{}", parent, stem, s.name)
        };
        map.entry(key).or_default().push(s.clone());
    }
    map
}

/// Create a single graph node for a function.
fn make_node(f: &FunctionRecord, f_smells: &[SmellIssue]) -> GraphNode {
    let critical_count = f_smells
        .iter()
        .filter(|s| matches!(s.severity, Severity::Critical))
        .count();
    let warning_count = f_smells
        .iter()
        .filter(|s| matches!(s.severity, Severity::Warning))
        .count();

    let (color, health) = if critical_count > 0 {
        ("#e74c3c", "critical")
    } else if warning_count > 0 {
        ("#f39c12", "warning")
    } else {
        ("#2ecc71", "healthy")
    };

    let mut tooltip = format!(
        "<b>{}</b><br>{}:{}<br>",
        f.name, f.file_path, f.line_start
    );
    if !f_smells.is_empty() {
        tooltip.push_str("<br><b>Issues:</b><br>");
        for s in f_smells {
            let icon = s.severity.icon();
            tooltip.push_str(&format!("{} {}: {}<br>", icon, s.category, s.message));
        }
    }

    let group = Path::new(&f.file_path)
        .parent()
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_default();

    GraphNode {
        id: f.key(),
        label: f.name.clone(),
        title: tooltip,
        color: color.to_string(),
        health: health.to_string(),
        size: f.size_lines,
        group,
    }
}

/// Generate pairwise edges from DuplicateGroups.
fn make_edges(duplicates: &[DuplicateGroup]) -> Vec<GraphEdge> {
    let mut edges = Vec::new();
    for group in duplicates {
        if group.functions.len() < 2 {
            continue;
        }
        for i in 0..group.functions.len() {
            for j in (i + 1)..group.functions.len() {
                let key_from = group.functions[i]
                    .get("key")
                    .and_then(|k| k.as_str())
                    .unwrap_or("")
                    .to_string();
                let key_to = group.functions[j]
                    .get("key")
                    .and_then(|k| k.as_str())
                    .unwrap_or("")
                    .to_string();

                if !key_from.is_empty() && !key_to.is_empty() {
                    edges.push(GraphEdge {
                        from: key_from,
                        to: key_to,
                        value: group.avg_similarity,
                        title: format!(
                            "{} duplicate ({:.2})",
                            group.similarity_type, group.avg_similarity
                        ),
                    });
                }
            }
        }
    }
    edges
}

/// Export the graph to an interactive HTML file using vis-network.
pub fn write_html(
    nodes: &[GraphNode],
    edges: &[GraphEdge],
    output_path: &Path,
) -> std::io::Result<()> {
    let nodes_json = serde_json::to_string(nodes).unwrap_or_else(|_| "[]".to_string());
    let edges_json = serde_json::to_string(edges).unwrap_or_else(|_| "[]".to_string());

    let html = format!(
        r##"<!DOCTYPE html>
<html>
<head>
    <title>X-RAY Codebase Visualization</title>
    <script type="text/javascript" src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
    <style type="text/css">
        body {{ font-family: 'Segoe UI', Tahoma, sans-serif; margin: 0; padding: 20px; background: #1a1a2e; color: #eee; }}
        h2 {{ color: #00d4ff; }}
        #legend {{ margin: 10px 0; }}
        #legend span {{ margin-right: 18px; }}
        .dot {{ display: inline-block; width: 12px; height: 12px; border-radius: 50%; margin-right: 4px; vertical-align: middle; }}
        #mynetwork {{ width: 100%; height: 85vh; border: 1px solid #333; border-radius: 8px; background: #16213e; }}
        #stats {{ margin-top: 8px; color: #aaa; font-size: 0.9em; }}
    </style>
</head>
<body>
    <h2>X-RAY — Codebase Health Graph</h2>
    <div id="legend">
        <span><span class="dot" style="background:#2ecc71"></span>Healthy</span>
        <span><span class="dot" style="background:#f39c12"></span>Warning</span>
        <span><span class="dot" style="background:#e74c3c"></span>Critical</span>
    </div>
    <div id="mynetwork"></div>
    <div id="stats"></div>
    <script type="text/javascript">
        var nodesData = {nodes_json};
        var edgesData = {edges_json};
        var nodes = new vis.DataSet(nodesData);
        var edges = new vis.DataSet(edgesData);
        var container = document.getElementById('mynetwork');
        var data = {{ nodes: nodes, edges: edges }};
        var options = {{
            nodes: {{
                shape: 'dot',
                font: {{ size: 14, color: '#ddd' }},
                scaling: {{ min: 8, max: 40, label: {{ enabled: true, min: 10, max: 20 }} }}
            }},
            edges: {{
                color: {{ color: '#555', highlight: '#00d4ff' }},
                smooth: false
            }},
            physics: {{
                stabilization: false,
                barnesHut: {{
                    gravitationalConstant: -80000,
                    springConstant: 0.001,
                    springLength: 200
                }}
            }},
            interaction: {{ hover: true, tooltipDelay: 100 }}
        }};
        var network = new vis.Network(container, data, options);
        // Stats
        var healthy = nodesData.filter(n => n.health === 'healthy').length;
        var warning = nodesData.filter(n => n.health === 'warning').length;
        var critical = nodesData.filter(n => n.health === 'critical').length;
        document.getElementById('stats').innerHTML =
            'Functions: ' + nodesData.length + ' | Edges: ' + edgesData.length +
            ' | Healthy: ' + healthy + ' | Warning: ' + warning + ' | Critical: ' + critical;
    </script>
</body>
</html>"##
    );

    // Ensure parent dir exists
    if let Some(parent) = output_path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(output_path, html)?;
    Ok(())
}
