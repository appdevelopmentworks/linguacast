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

fn presets_path(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_config_dir()
        .map_err(|e| format!("cannot resolve config dir: {e}"))?;
    fs::create_dir_all(&dir).map_err(|e| format!("cannot create config dir: {e}"))?;
    Ok(dir.join("presets.json"))
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
