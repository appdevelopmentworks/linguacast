//! Tauri commands exposed to the frontend.
//!
//! The UI never talks to the sidecar directly (architecture.md §5): it invokes
//! these commands and Rust proxies over internal HTTP.

use std::sync::Arc;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tauri::{Emitter, State};

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

// --- Settings + secrets (Session 3) ---

#[tauri::command]
pub fn get_settings(app: tauri::AppHandle) -> Result<crate::config::Settings, String> {
    crate::config::load_settings(&app)
}

#[tauri::command]
pub fn save_settings(
    app: tauri::AppHandle,
    settings: crate::config::Settings,
) -> Result<(), String> {
    crate::config::save_settings(&app, &settings)
}

const OPENROUTER_KEY_NAME: &str = "openrouter_api_key";

#[tauri::command]
pub fn set_openrouter_key(key: String) -> Result<(), String> {
    crate::secrets::set_secret(OPENROUTER_KEY_NAME, &key)
}

/// Only reports presence — the key itself never travels to the UI.
#[tauri::command]
pub fn has_openrouter_key() -> Result<bool, String> {
    Ok(crate::secrets::get_secret(OPENROUTER_KEY_NAME)?.is_some())
}

// --- Session 3: translation (proxy to the sidecar translate stage) ---

#[derive(Serialize, Deserialize)]
pub struct TranslateBackends {
    ollama: serde_json::Value,
    lmstudio: serde_json::Value,
}

#[tauri::command]
pub async fn translate_backends(
    manager: State<'_, Arc<SidecarManager>>,
) -> Result<TranslateBackends, String> {
    let url = format!("{}/translate/backends", manager.base_url());
    let resp = reqwest::get(&url)
        .await
        .map_err(|e| format!("cannot reach sidecar: {e}"))?;
    resp.json::<TranslateBackends>()
        .await
        .map_err(|e| format!("invalid backends response: {e}"))
}

#[derive(Serialize, Deserialize)]
pub struct TranslateSample {
    start: f64,
    end: f64,
    src: String,
    dst: String,
}

#[derive(Serialize, Deserialize)]
pub struct TranslateSrtResult {
    tier: String,
    model: String,
    base_url: String,
    segment_count: u32,
    translated_srt_path: String,
    samples: Vec<TranslateSample>,
}

#[tauri::command]
pub async fn translate_srt(
    app: tauri::AppHandle,
    manager: State<'_, Arc<SidecarManager>>,
    srt_path: String,
    output_dir: String,
    model: Option<String>,
) -> Result<TranslateSrtResult, String> {
    let settings = crate::config::load_settings(&app)?;
    let chosen_model = model.unwrap_or(settings.translation_model);

    let _ = app.emit(
        "linguacast://progress",
        serde_json::json!({
            "stage": "translate",
            "message": format!("和訳中…（モデル: {chosen_model}）"),
        }),
    );

    // The cloud key only travels Rust -> sidecar over loopback, never to the UI.
    let openrouter_key = crate::secrets::get_secret(OPENROUTER_KEY_NAME)?;

    let url = format!("{}/translate/srt", manager.base_url());
    let body = serde_json::json!({
        "srt_path": srt_path,
        "output_dir": output_dir,
        "model": chosen_model,
        "source_lang": settings.source_lang,
        "openrouter_key": openrouter_key,
        "openrouter_model": settings.openrouter_model,
    });

    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(6 * 3600))
        .build()
        .map_err(|e| format!("failed to build HTTP client: {e}"))?;

    let resp = client
        .post(&url)
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("cannot reach sidecar: {e}"))?;

    if resp.status().is_success() {
        resp.json::<TranslateSrtResult>()
            .await
            .map_err(|e| format!("invalid translation response: {e}"))
    } else {
        let status = resp.status();
        let detail = resp.text().await.unwrap_or_default();
        Err(format!("translation failed ({status}): {detail}"))
    }
}

// --- Session 2: transcription (proxy to the sidecar STT stage) ---

#[derive(Serialize, Deserialize)]
pub struct SttSegment {
    start: f64,
    end: f64,
    text: String,
}

#[derive(Serialize, Deserialize)]
pub struct TranscribeResult {
    language: String,
    duration: f64,
    backend: String,
    device: String,
    model: String,
    segment_count: u32,
    srt_path: Option<String>,
    segments: Vec<SttSegment>,
}

#[tauri::command]
pub async fn transcribe(
    app: tauri::AppHandle,
    manager: State<'_, Arc<SidecarManager>>,
    audio_path: String,
    output_dir: String,
    model_size: Option<String>,
) -> Result<TranscribeResult, String> {
    let _ = app.emit(
        "linguacast://progress",
        serde_json::json!({
            "stage": "stt",
            "message": "文字起こし中…（初回はモデルの読み込みに時間がかかります）",
        }),
    );

    let url = format!("{}/stt/transcribe", manager.base_url());
    let body = serde_json::json!({
        "audio_path": audio_path,
        "output_dir": output_dir,
        "model_size": model_size.unwrap_or_else(|| "large-v3".to_string()),
    });

    // Transcription can run for many minutes on long videos.
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(6 * 3600))
        .build()
        .map_err(|e| format!("failed to build HTTP client: {e}"))?;

    let resp = client
        .post(&url)
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("cannot reach sidecar: {e}"))?;

    if resp.status().is_success() {
        resp.json::<TranscribeResult>()
            .await
            .map_err(|e| format!("invalid transcription response: {e}"))
    } else {
        let status = resp.status();
        let detail = resp.text().await.unwrap_or_default();
        Err(format!("transcription failed ({status}): {detail}"))
    }
}
