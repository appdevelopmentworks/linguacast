//! User configuration persisted as JSON in the app config directory.
//!
//! For v0.1 this holds the preset channel list (requirements FR-11), which is
//! user-editable (add/remove/reorder/categorize) and seeded with defaults.

use std::fs;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager};

#[derive(Serialize, Deserialize, Clone)]
pub struct PresetChannel {
    pub label: String,
    pub url: String,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct PresetCategory {
    pub category: String,
    pub channels: Vec<PresetChannel>,
}

pub type Presets = Vec<PresetCategory>;

fn channel(label: &str, url: &str) -> PresetChannel {
    PresetChannel {
        label: label.to_string(),
        url: url.to_string(),
    }
}

/// Initial presets from requirements FR-11.
fn default_presets() -> Presets {
    vec![
        PresetCategory {
            category: "AI".to_string(),
            channels: vec![
                channel("Andrej Karpathy", "https://www.youtube.com/@AndrejKarpathy"),
                channel("DeepLearning.AI", "https://www.youtube.com/@Deeplearningai"),
            ],
        },
        PresetCategory {
            category: "プログラミング / IT".to_string(),
            channels: vec![channel(
                "freeCodeCamp",
                "https://www.youtube.com/@freecodecamp",
            )],
        },
        PresetCategory {
            category: "投資".to_string(),
            channels: vec![
                channel("Point72", "https://www.youtube.com/@point72careers"),
                channel(
                    "The Master Investor Podcast",
                    "https://www.youtube.com/@TheMasterInvestorPodcast",
                ),
            ],
        },
    ]
}

/// App data/config root. `LINGUACAST_DATA_DIR` overrides the OS location —
/// used in development so artifacts land in a user-visible directory (Claude
/// Code's sandbox virtualizes AppData writes into an invisible overlay).
pub fn data_root(app: &AppHandle) -> Result<PathBuf, String> {
    if let Ok(dir) = std::env::var("LINGUACAST_DATA_DIR") {
        if !dir.trim().is_empty() {
            let p = PathBuf::from(dir);
            fs::create_dir_all(&p).map_err(|e| format!("cannot create data dir: {e}"))?;
            return Ok(p);
        }
    }
    let dir = app
        .path()
        .app_config_dir()
        .map_err(|e| format!("cannot resolve config dir: {e}"))?;
    fs::create_dir_all(&dir).map_err(|e| format!("cannot create config dir: {e}"))?;
    Ok(dir)
}

fn presets_path(app: &AppHandle) -> Result<PathBuf, String> {
    Ok(data_root(app)?.join("presets.json"))
}

/// Load presets, seeding defaults on first run.
pub fn load_presets(app: &AppHandle) -> Result<Presets, String> {
    let path = presets_path(app)?;
    if path.exists() {
        let txt = fs::read_to_string(&path).map_err(|e| format!("cannot read presets: {e}"))?;
        serde_json::from_str(&txt).map_err(|e| format!("cannot parse presets: {e}"))
    } else {
        let defaults = default_presets();
        save_presets(app, &defaults)?;
        Ok(defaults)
    }
}

pub fn save_presets(app: &AppHandle, presets: &Presets) -> Result<(), String> {
    let path = presets_path(app)?;
    let txt = serde_json::to_string_pretty(presets)
        .map_err(|e| format!("cannot serialize presets: {e}"))?;
    fs::write(&path, txt).map_err(|e| format!("cannot write presets: {e}"))
}

// --- App settings (translation model, OpenRouter slug, source language) ---

#[derive(Serialize, Deserialize, Clone)]
#[serde(default)]
pub struct Settings {
    /// Default translation model (benchmark default: translategemma:27b).
    /// Switchable in the UI to qwen3.6 / gemma4 / any LM Studio model.
    pub translation_model: String,
    /// OpenRouter model slug for the cloud tier (e.g. anthropic/claude-...).
    pub openrouter_model: Option<String>,
    /// Source language code for transcription/translation.
    pub source_lang: String,
    /// VOICEVOX style id for narrator/host lines (3 = ずんだもん ノーマル).
    pub narrator_voice: u32,
    /// VOICEVOX style id for guest lines in dialogue scripts (2 = 四国めたん ノーマル).
    pub guest_voice: u32,
    /// Edge TTS voice for narrator/host lines.
    pub edge_narrator_voice: String,
    /// Edge TTS voice for guest lines in dialogue scripts.
    pub edge_guest_voice: String,
    /// STT engine: "local" (faster-whisper) or "groq" (cloud, free tier).
    pub stt_engine: String,
    /// Groq Whisper model (turbo is the fast, near-equal-accuracy default).
    pub groq_model: String,
    /// Cloud LLM provider for the third fallback tier: "openrouter" | "groq".
    pub cloud_llm_provider: String,
    /// Groq LLM model id (picked from the Groq catalogue in settings).
    pub groq_llm_model: String,
    /// Enable LLM chain-of-thought ("thinking"). Off by default: translation /
    /// summarization / dub never need it and thinking models (Qwen3 etc.) are
    /// 10-100x slower with it on. Applies to local and cloud tiers.
    pub thinking: bool,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            translation_model: "translategemma:27b".to_string(),
            openrouter_model: None,
            source_lang: "en".to_string(),
            narrator_voice: 3,
            guest_voice: 2,
            edge_narrator_voice: "ja-JP-NanamiNeural".to_string(),
            edge_guest_voice: "ja-JP-KeitaNeural".to_string(),
            stt_engine: "local".to_string(),
            groq_model: "whisper-large-v3-turbo".to_string(),
            cloud_llm_provider: "openrouter".to_string(),
            groq_llm_model: String::new(),
            thinking: false,
        }
    }
}

fn settings_path(app: &AppHandle) -> Result<PathBuf, String> {
    Ok(data_root(app)?.join("settings.json"))
}

pub fn load_settings(app: &AppHandle) -> Result<Settings, String> {
    let path = settings_path(app)?;
    if path.exists() {
        let txt = fs::read_to_string(&path).map_err(|e| format!("cannot read settings: {e}"))?;
        serde_json::from_str(&txt).map_err(|e| format!("cannot parse settings: {e}"))
    } else {
        let defaults = Settings::default();
        save_settings(app, &defaults)?;
        Ok(defaults)
    }
}

pub fn save_settings(app: &AppHandle, settings: &Settings) -> Result<(), String> {
    let path = settings_path(app)?;
    let txt = serde_json::to_string_pretty(settings)
        .map_err(|e| format!("cannot serialize settings: {e}"))?;
    fs::write(&path, txt).map_err(|e| format!("cannot write settings: {e}"))
}
