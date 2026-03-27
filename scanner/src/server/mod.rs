//! HTTP server — axum-based, port of ui_server.py.
//!
//! Serves the embedded ui.html and exposes all API endpoints.

pub mod routes;
pub mod state;

use axum::{
    Router,
    http::{Method, StatusCode, header},
    response::IntoResponse,
    routing::{get, post},
};
use std::net::SocketAddr;
use std::sync::Arc;
use tower_http::cors::{Any, CorsLayer};
use tracing::info;

use self::state::AppState;

/// Embedded ui.html — loaded at compile time from the project root.
/// Falls back to a placeholder if the file isn't there at build time.
const UI_HTML: &str = include_str!("../../../ui.html");

/// Build the axum router with all routes.
pub fn build_router(shared: Arc<AppState>) -> Router {
    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods([Method::GET, Method::POST, Method::OPTIONS])
        .allow_headers(Any);

    Router::new()
        // ── Static / UI ──────────────────────────────────────────────
        .route("/", get(serve_ui))
        .route("/ui.html", get(serve_ui))
        // ── GET API ──────────────────────────────────────────────────
        .route("/api/info", get(routes::info))
        .route("/api/browse", get(routes::browse))
        .route("/api/scan-result", get(routes::scan_result))
        .route("/api/scan-progress", get(routes::scan_progress))
        // ── POST API – scanning ──────────────────────────────────────
        .route("/api/scan", post(routes::scan))
        .route("/api/abort", post(routes::abort))
        // ── POST API – fixers ────────────────────────────────────────
        .route("/api/preview-fix", post(routes::preview_fix))
        .route("/api/apply-fix", post(routes::apply_fix))
        // ── POST API – analyzers ─────────────────────────────────────
        .route("/api/health", post(routes::health))
        .route("/api/smells", post(routes::smells))
        .route("/api/dead-code", post(routes::dead_code))
        .route("/api/duplicates", post(routes::duplicates))
        .route("/api/format", post(routes::format_check))
        .route("/api/typecheck", post(routes::type_check))
        .route("/api/connection-test", post(routes::connection_test))
        .route("/api/release-readiness", post(routes::release_readiness))
        .route("/api/remediation-time", post(routes::remediation_time))
        // ── POST API – SATD / git / security / temporal ──────────────
        .route("/api/satd", post(routes::satd))
        .route("/api/git-hotspots", post(routes::git_hotspots))
        .route("/api/imports", post(routes::imports))
        .route("/api/ruff", post(routes::ruff))
        .route("/api/bandit", post(routes::bandit))
        .route("/api/temporal-coupling", post(routes::temporal_coupling))
        .route("/api/ai-detect", post(routes::ai_detect))
        .route("/api/web-smells", post(routes::web_smells))
        .route("/api/test-gen", post(routes::test_gen))
        .route("/api/typecheck-pyright", post(routes::type_check_pyright))
        // ── POST API – PM dashboard ──────────────────────────────────
        .route("/api/risk-heatmap", post(routes::risk_heatmap))
        .route("/api/module-cards", post(routes::module_cards))
        .route("/api/confidence", post(routes::confidence))
        .route("/api/sprint-batches", post(routes::sprint_batches))
        .route("/api/architecture", post(routes::architecture))
        .route("/api/call-graph", post(routes::call_graph))
        .route("/api/project-review", post(routes::project_review))
        // ── POST API – graph ─────────────────────────────────────────
        .route("/api/circular-calls", post(routes::circular_calls))
        .route("/api/coupling", post(routes::coupling))
        .route("/api/unused-imports", post(routes::unused_imports))
        // ── SARIF ────────────────────────────────────────────────────
        .route("/api/sarif", post(routes::sarif_export))
        .layer(cors)
        .with_state(shared)
}

/// Serve embedded ui.html.
async fn serve_ui() -> impl IntoResponse {
    (
        StatusCode::OK,
        [(header::CONTENT_TYPE, "text/html; charset=utf-8")],
        UI_HTML,
    )
}

/// Start the server on the given port.
pub async fn run_server(port: u16) -> anyhow::Result<()> {
    let shared = Arc::new(AppState::new());
    let app = build_router(shared);
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    info!("X-Ray Rust server listening on http://{}", addr);
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}
