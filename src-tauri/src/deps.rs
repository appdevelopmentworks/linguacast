//! Startup/pre-run health checks for external runtime dependencies.
//!
//! A missing tool is reported (with Japanese guidance) rather than crashing —
//! the UI surfaces it before the user starts a job.

use serde::Serialize;

use crate::external::run_capture;

#[derive(Serialize)]
pub struct ToolStatus {
    name: String,
    available: bool,
    version: Option<String>,
    /// Japanese hint shown in the UI when the tool is missing.
    hint: Option<String>,
}

#[derive(Serialize)]
pub struct DependencyReport {
    tools: Vec<ToolStatus>,
    all_ok: bool,
}

async fn probe(name: &str, version_args: &[&str], hint: &str) -> ToolStatus {
    match run_capture(name, version_args.iter().copied()).await {
        Ok(out) => ToolStatus {
            name: name.to_string(),
            available: true,
            version: Some(out.lines().next().unwrap_or("").trim().to_string()),
            hint: None,
        },
        Err(_) => ToolStatus {
            name: name.to_string(),
            available: false,
            version: None,
            hint: Some(hint.to_string()),
        },
    }
}

pub async fn check_all() -> DependencyReport {
    let ytdlp = probe(
        "yt-dlp",
        &["--version"],
        "yt-dlp が見つかりません。https://github.com/yt-dlp/yt-dlp からインストールし、PATH を通してください。",
    )
    .await;
    let ffmpeg = probe(
        "ffmpeg",
        &["-version"],
        "ffmpeg が見つかりません。https://ffmpeg.org からインストールし、PATH を通してください。",
    )
    .await;
    let ffprobe = probe(
        "ffprobe",
        &["-version"],
        "ffprobe が見つかりません（通常は ffmpeg に同梱）。ffmpeg のインストールを確認してください。",
    )
    .await;

    let all_ok = ytdlp.available && ffmpeg.available && ffprobe.available;
    DependencyReport {
        tools: vec![ytdlp, ffmpeg, ffprobe],
        all_ok,
    }
}
