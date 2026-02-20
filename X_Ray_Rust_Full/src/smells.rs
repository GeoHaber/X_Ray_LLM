// src/smells.rs — Code smell detection (unified, zero duplication)
//
// All threshold-based checks on FunctionRecord and ClassRecord.
// Single entry point: detect() → Vec<SmellIssue>

use crate::config::SmellThresholds;
use crate::types::{ClassRecord, FunctionRecord, Severity, SmellIssue};

/// Detect code smells in extracted functions and classes
pub fn detect(
    functions: &[FunctionRecord],
    classes: &[ClassRecord],
    thresholds: &SmellThresholds,
) -> Vec<SmellIssue> {
    let mut issues = Vec::new();

    for f in functions {
        check_function(f, thresholds, &mut issues);
    }
    for c in classes {
        check_class(c, thresholds, &mut issues);
    }

    // Sort: critical first, then by file/line
    issues.sort_by(|a, b| {
        let sev_order = |s: &Severity| match s {
            Severity::Critical => 0,
            Severity::Warning => 1,
            Severity::Info => 2,
        };
        sev_order(&a.severity)
            .cmp(&sev_order(&b.severity))
            .then(a.file_path.cmp(&b.file_path))
            .then(a.line.cmp(&b.line))
    });

    issues
}

fn emit(
    issues: &mut Vec<SmellIssue>,
    file_path: &str,
    line: u32,
    end_line: u32,
    name: &str,
    category: &str,
    severity: Severity,
    message: String,
    suggestion: &str,
    metric_value: u32,
) {
    issues.push(SmellIssue {
        file_path: file_path.to_string(),
        line,
        end_line,
        category: category.to_string(),
        severity,
        message,
        suggestion: suggestion.to_string(),
        name: name.to_string(),
        metric_value,
        source: "xray".to_string(),
        rule_code: String::new(),
        fixable: false,
        confidence: String::new(),
    });
}

fn check_function(f: &FunctionRecord, t: &SmellThresholds, issues: &mut Vec<SmellIssue>) {
    // Long function
    if f.size_lines >= t.very_long_function {
        emit(
            issues, &f.file_path, f.line_start, f.line_end, &f.name,
            "LONG-FUNCTION", Severity::Critical,
            format!("Function '{}' is {} lines (limit: {})", f.name, f.size_lines, t.very_long_function),
            "Split into smaller focused functions. Extract logical blocks.",
            f.size_lines,
        );
    } else if f.size_lines >= t.long_function {
        emit(
            issues, &f.file_path, f.line_start, f.line_end, &f.name,
            "LONG-FUNCTION", Severity::Warning,
            format!("Function '{}' is {} lines (limit: {})", f.name, f.size_lines, t.long_function),
            "Consider splitting into smaller functions.",
            f.size_lines,
        );
    }

    // Deep nesting
    if f.nesting_depth >= t.very_deep_nesting {
        emit(
            issues, &f.file_path, f.line_start, f.line_end, &f.name,
            "DEEP-NESTING", Severity::Critical,
            format!("Function '{}' has nesting depth {} (limit: {})", f.name, f.nesting_depth, t.very_deep_nesting),
            "Use early returns, guard clauses, or extract nested blocks.",
            f.nesting_depth,
        );
    } else if f.nesting_depth >= t.deep_nesting {
        emit(
            issues, &f.file_path, f.line_start, f.line_end, &f.name,
            "DEEP-NESTING", Severity::Warning,
            format!("Function '{}' has nesting depth {} (limit: {})", f.name, f.nesting_depth, t.deep_nesting),
            "Flatten with early returns or extract helper functions.",
            f.nesting_depth,
        );
    }

    // High complexity
    if f.complexity >= t.very_high_complexity {
        emit(
            issues, &f.file_path, f.line_start, f.line_end, &f.name,
            "COMPLEX-FUNCTION", Severity::Critical,
            format!("Function '{}' has cyclomatic complexity {} (limit: {})", f.name, f.complexity, t.very_high_complexity),
            "Decompose into smaller, single-responsibility functions.",
            f.complexity,
        );
    } else if f.complexity >= t.high_complexity {
        emit(
            issues, &f.file_path, f.line_start, f.line_end, &f.name,
            "COMPLEX-FUNCTION", Severity::Warning,
            format!("Function '{}' has cyclomatic complexity {} (limit: {})", f.name, f.complexity, t.high_complexity),
            "Simplify branching logic. Consider lookup tables or strategy pattern.",
            f.complexity,
        );
    }

    // Too many params
    if f.parameters.len() as u32 >= t.too_many_params {
        emit(
            issues, &f.file_path, f.line_start, f.line_end, &f.name,
            "TOO-MANY-PARAMS", Severity::Warning,
            format!("Function '{}' has {} parameters (limit: {})", f.name, f.parameters.len(), t.too_many_params),
            "Group related parameters into a dataclass or config object.",
            f.parameters.len() as u32,
        );
    }

    // Missing docstring
    if f.docstring.is_none()
        && f.size_lines >= t.missing_docstring_size
        && !f.name.starts_with('_')
    {
        emit(
            issues, &f.file_path, f.line_start, f.line_end, &f.name,
            "MISSING-DOCSTRING", Severity::Info,
            format!("Function '{}' ({} lines) has no docstring", f.name, f.size_lines),
            "Add a docstring explaining purpose, parameters, and return value.",
            f.size_lines,
        );
    }

    // Too many returns
    if f.return_count >= t.too_many_returns {
        emit(
            issues, &f.file_path, f.line_start, f.line_end, &f.name,
            "TOO-MANY-RETURNS", Severity::Warning,
            format!("Function '{}' has {} return statements (limit: {})", f.name, f.return_count, t.too_many_returns),
            "Consolidate exit points. Consider a result variable.",
            f.return_count,
        );
    }

    // Too many branches
    if f.branch_count >= t.too_many_branches {
        emit(
            issues, &f.file_path, f.line_start, f.line_end, &f.name,
            "TOO-MANY-BRANCHES", Severity::Warning,
            format!("Function '{}' has {} branches (limit: {})", f.name, f.branch_count, t.too_many_branches),
            "Simplify with lookup tables, strategy pattern, or early returns.",
            f.branch_count,
        );
    }

    // Boolean blindness
    if let Some(ref ret) = f.return_type {
        if ret.to_lowercase().contains("bool") {
            let good_prefixes = [
                "is_", "has_", "can_", "should_", "check_", "validate_",
                "contains_", "exists_",
            ];
            if !good_prefixes.iter().any(|p| f.name.starts_with(p)) {
                emit(
                    issues, &f.file_path, f.line_start, f.line_end, &f.name,
                    "BOOLEAN-BLINDNESS", Severity::Info,
                    format!("Function '{}' returns bool but name doesn't indicate a question", f.name),
                    "Rename to is_/has_/can_/should_/check_ prefix for clarity.",
                    0,
                );
            }
        }
    }
}

fn check_class(c: &ClassRecord, t: &SmellThresholds, issues: &mut Vec<SmellIssue>) {
    // God class
    if c.method_count >= t.god_class {
        emit(
            issues, &c.file_path, c.line_start, c.line_end, &c.name,
            "GOD-CLASS", Severity::Critical,
            format!("Class '{}' has {} methods (limit: {})", c.name, c.method_count, t.god_class),
            "Split into focused classes with single responsibility.",
            c.method_count,
        );
    }

    // Large class
    if c.size_lines >= t.large_class {
        emit(
            issues, &c.file_path, c.line_start, c.line_end, &c.name,
            "LARGE-CLASS", Severity::Warning,
            format!("Class '{}' is {} lines (limit: {})", c.name, c.size_lines, t.large_class),
            "Consider splitting into smaller, focused classes.",
            c.size_lines,
        );
    }

    // Missing class docstring
    if c.docstring.is_none() && c.size_lines > 30 {
        emit(
            issues, &c.file_path, c.line_start, c.line_end, &c.name,
            "MISSING-CLASS-DOCSTRING", Severity::Info,
            format!("Class '{}' ({} lines) has no docstring", c.name, c.size_lines),
            "Add a docstring explaining the class's responsibility.",
            c.size_lines,
        );
    }

    // Dataclass candidate
    if c.method_count <= 3 && c.has_init && c.base_classes.is_empty() {
        emit(
            issues, &c.file_path, c.line_start, c.line_end, &c.name,
            "DATACLASS-CANDIDATE", Severity::Info,
            format!("Class '{}' has only {} methods \u{2014} consider @dataclass", c.name, c.method_count),
            "If this class mainly holds data, convert to @dataclass for less boilerplate.",
            c.method_count,
        );
    }
}

/// Generate summary counts
pub fn summary(issues: &[SmellIssue]) -> (usize, usize, usize) {
    let critical = issues.iter().filter(|i| i.severity == Severity::Critical).count();
    let warning = issues.iter().filter(|i| i.severity == Severity::Warning).count();
    let info = issues.iter().filter(|i| i.severity == Severity::Info).count();
    (critical, warning, info)
}
