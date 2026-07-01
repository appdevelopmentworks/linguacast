//! Tauri commands exposed to the frontend.
//!
//! The UI never talks to the sidecar directly (architecture.md §5): it invokes
//! these commands and Rust proxies over internal HTTP.

use std::sync::Arc;

use serde::{Deserialize, Serialize};
use tauri::State;

use crate::sidecar::SidecarManager;

/// Health result shaped for the UI. `reachable == false` is a normal, non-error
/// outcome (fallback contract) — the command returns Ok with a `detail` message.
#[derive(Serialize)]
pub struct SidecarHealth {
    reachable: bool,
    status: Option<String>,
    service: Option<String>,
    version: Option<String>,
    detail: Option<String>,
}

impl SidecarHealth {
    fn unreachable(detail: String) -> Self {
        Self {
            reachable: false,
            status: None,
            service: None,
            version: None,
            detail: Some(detail),
        }
    }
}

/// Shape of the sidecar's /health JSON payload.
#[derive(Deserialize)]
struct HealthResponse {
    status: String,
    service: String,
    version: String,
}

#[tauri::command]
pub async fn ping_sidecar(
    manager: State<'_, Arc<SidecarManager>>,
) -> Result<SidecarHealth, String> {
    let url = format!("{}/health", manager.base_url());
    let client = reqwest::Client::new();

    match client.get(&url).send().await {
        Ok(resp) if resp.status().is_success() => match resp.json::<HealthResponse>().await {
            Ok(body) => Ok(SidecarHealth {
                reachable: true,
                status: Some(body.status),
                service: Some(body.service),
                version: Some(body.version),
                detail: None,
            }),
            Err(e) => Ok(SidecarHealth::unreachable(format!(
                "invalid health payload: {e}"
            ))),
        },
        Ok(resp) => Ok(SidecarHealth::unreachable(format!(
            "sidecar returned status {}",
            resp.status()
        ))),
        Err(e) => Ok(SidecarHealth::unreachable(format!(
            "cannot reach sidecar: {e}"
        ))),
    }
}

#[derive(Serialize)]
pub struct SidecarStatus {
    port: u16,
    base_url: String,
}

#[tauri::command]
pub fn sidecar_status(manager: State<'_, Arc<SidecarManager>>) -> SidecarStatus {
    SidecarStatus {
        port: manager.port(),
        base_url: manager.base_url(),
    }
}

// --- Session 1: media input / audio extraction ---

#[tauri::command]
pub async fn check_dependencies() -> crate::deps::DependencyReport {
    crate::deps::check_all().await
}

#[tauri::command]
pub async fn fetch_metadata(url: String) -> Result<crate::media::MediaMeta, String> {
    crate::media::fetch_metadata(&url).await
}

#[tauri::command]
pub async fn prepare_media(
    app: tauri::AppHandle,
    url: String,
) -> Result<crate::media::Job, String> {
    crate::media::prepare_media(&app, &url).await
}

#[tauri::command]
pub async fn list_channel_uploads(
    channel_url: String,
    limit: Option<u32>,
) -> Result<Vec<crate::media::VideoEntry>, String> {
    crate::media::list_channel_uploads(&channel_url, limit).await
}

#[tauri::command]
pub fn get_presets(app: tauri::AppHandle) -> Result<crate::config::Presets, String> {
    crate::config::load_presets(&app)
}

#[tauri::command]
pub fn save_presets(app: tauri::AppHandle, presets: crate::config::Presets) -> Result<(), String> {
    crate::config::save_presets(&app, &presets)
}
