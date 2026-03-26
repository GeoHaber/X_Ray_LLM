//! X-Ray Config — Project-level configuration from pyproject.toml.
//! Rust port of xray/config.py.

use serde::Deserialize;
use std::path::Path;

/// Project-level X-Ray configuration.
#[derive(Debug, Clone)]
pub struct XRayConfig {
    pub severity: String,
    pub exclude_patterns: Vec<String>,
    pub output_format: String,
    pub incremental: bool,
    pub parallel: bool,
    pub rules_dir: String,
    pub suppress_rules: Vec<String>,
    pub max_file_size: u64,
}

impl Default for XRayConfig {
    fn default() -> Self {
        XRayConfig {
            severity: "MEDIUM".to_string(),
            exclude_patterns: vec![],
            output_format: "text".to_string(),
            incremental: false,
            parallel: true,
            rules_dir: String::new(),
            suppress_rules: vec![],
            max_file_size: 1_048_576,
        }
    }
}

/// Intermediate deserialization struct for pyproject.toml.
#[derive(Deserialize, Default)]
struct PyProject {
    #[serde(default)]
    tool: ToolSection,
}

#[derive(Deserialize, Default)]
struct ToolSection {
    #[serde(default)]
    xray: Option<XRayToml>,
}

#[derive(Deserialize, Default)]
struct XRayToml {
    severity: Option<String>,
    exclude: Option<Vec<String>>,
    #[serde(rename = "output-format")]
    output_format: Option<String>,
    incremental: Option<bool>,
    parallel: Option<bool>,
    #[serde(rename = "rules-dir")]
    rules_dir: Option<String>,
    suppress: Option<Vec<String>>,
    #[serde(rename = "max-file-size")]
    max_file_size: Option<u64>,
}

impl XRayConfig {
    /// Load config from [tool.xray] in pyproject.toml.
    pub fn from_pyproject(project_root: &str) -> Self {
        let mut config = XRayConfig::default();
        let pyproject_path = Path::new(project_root).join("pyproject.toml");

        if !pyproject_path.is_file() {
            return config;
        }

        let content = match std::fs::read_to_string(&pyproject_path) {
            Ok(c) => c,
            Err(_) => return config,
        };

        let pyproject: PyProject = match toml::from_str(&content) {
            Ok(p) => p,
            Err(e) => {
                eprintln!("Warning: Failed to parse pyproject.toml: {e}");
                return config;
            }
        };

        let xray = match pyproject.tool.xray {
            Some(x) => x,
            None => return config,
        };

        if let Some(sev) = xray.severity {
            let upper = sev.to_uppercase();
            if ["HIGH", "MEDIUM", "LOW"].contains(&upper.as_str()) {
                config.severity = upper;
            }
        }

        if let Some(exclude) = xray.exclude {
            config.exclude_patterns = exclude;
        }

        if let Some(fmt) = xray.output_format {
            let lower = fmt.to_lowercase();
            if ["text", "json", "sarif"].contains(&lower.as_str()) {
                config.output_format = lower;
            }
        }

        if let Some(inc) = xray.incremental {
            config.incremental = inc;
        }

        if let Some(par) = xray.parallel {
            config.parallel = par;
        }

        if let Some(dir) = xray.rules_dir {
            config.rules_dir = dir;
        }

        if let Some(suppress) = xray.suppress {
            config.suppress_rules = suppress;
        }

        if let Some(size) = xray.max_file_size {
            config.max_file_size = size;
        }

        config
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_config() {
        let cfg = XRayConfig::default();
        assert_eq!(cfg.severity, "MEDIUM");
        assert_eq!(cfg.output_format, "text");
        assert!(cfg.parallel);
        assert!(!cfg.incremental);
        assert_eq!(cfg.max_file_size, 1_048_576);
    }

    #[test]
    fn test_from_nonexistent_pyproject() {
        let cfg = XRayConfig::from_pyproject("/nonexistent/path");
        assert_eq!(cfg.severity, "MEDIUM");
    }
}
