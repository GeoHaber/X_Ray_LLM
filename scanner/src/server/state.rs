//! Shared application state — port of services/app_state.py.

use std::sync::Mutex;

use crate::ScanResult;

/// Shared mutable state across request handlers.
pub struct AppState {
    pub last_scan_result: Mutex<Option<ScanResult>>,
    pub scan_progress: Mutex<Option<serde_json::Value>>,
    pub scan_elapsed_ms: Mutex<f64>,
    pub abort: std::sync::atomic::AtomicBool,
}

impl AppState {
    pub fn new() -> Self {
        Self {
            last_scan_result: Mutex::new(None),
            scan_progress: Mutex::new(None),
            scan_elapsed_ms: Mutex::new(0.0),
            abort: std::sync::atomic::AtomicBool::new(false),
        }
    }

    pub fn reset_scan(&self) {
        *self.last_scan_result.lock().unwrap() = None;
        *self.scan_progress.lock().unwrap() = None;
        *self.scan_elapsed_ms.lock().unwrap() = 0.0;
        self.abort.store(false, std::sync::atomic::Ordering::Relaxed);
    }
}
