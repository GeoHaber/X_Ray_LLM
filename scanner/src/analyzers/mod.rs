//! Code analyzers — smells, health checks, connections, security, PM dashboard.
//! Rust port of analyzers/ package.

pub mod smells;
pub mod health;
pub mod connections;
pub mod detection;
pub mod format_check;
pub mod graph;
pub mod satd;
pub mod git_analyzer;
pub mod security;
pub mod temporal;
pub mod pm_dashboard;
