//! Stage 1-2 of the pipeline: ingest (yt-dlp) and extract (ffmpeg).
//!
//! From a URL we fetch metadata (title/duration/chapters), download the best
//! audio stream, and transcode to 16 kHz mono WAV (Whisper-ready). Artifacts and
//! a `job.json` are persisted under a per-job working directory so later stages
//! (STT onward, in the sidecar) can pick them up and the work is resumable.

use std::fs;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager};
use uuid::Uuid;

use crate::external::run_capture;

/// Length-based routing thresholds (seconds). These decide the downstream
/// summarization strategy (single-pass vs hierarchical) in later sessions.
const SHORT_MAX_SEC: f64 = 15.0 * 60.0;
const MEDIUM_MAX_SEC: f64 = 90.0 * 60.0;

/// How many recent uploads to list when a preset channel is opened.
const DEFAULT_CHANNEL_LIMIT: u32 = 15;

#[derive(Serialize, Deserialize, Clone)]
pub struct Chapter {
    pub title: String,
    pub start: f64,
    pub end: f64,
}

#[derive(Serialize, Deserialize, Clone, Copy)]
#[serde(rename_all = "snake_case")]
pub enum RoutingClass {
    Short,
    Medium,
    Long,
}

impl RoutingClass {
    fn from_duration(sec: f64) -> Self {
        if sec <= SHORT_MAX_SEC {
            Self::Short
        } else if sec <= MEDIUM_MAX_SEC {
            Self::Medium
        } else {
            Self::Long
        }
    }
}

#[derive(Serialize, Deserialize, Clone)]
pub struct MediaMeta {
    pub source_url: String,
    pub title: String,
    pub duration_sec: f64,
    pub chapters: Vec<Chapter>,
    pub routing: RoutingClass,
}

#[derive(Serialize, Deserialize, Clone, Default)]
pub struct JobArtifacts {
    /// Downloaded best-audio file (original container).
    pub source_audio: Option<String>,
    /// 16 kHz mono WAV extracted for STT.
    pub extracted_wav: Option<String>,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct Job {
    pub id: String,
    pub work_dir: String,
    /// Last successfully completed stage: metadata | ingested | extracted.
    pub stage: String,
    pub meta: MediaMeta,
    pub artifacts: JobArtifacts,
}

#[derive(Serialize)]
pub struct VideoEntry {
    pub id: String,
    pub title: String,
    pub url: String,
    pub duration_sec: Option<f64>,
}

// --- yt-dlp JSON shapes (only the fields we need) ---

#[derive(Deserialize)]
struct YtChapter {
    title: Option<String>,
    start_time: Option<f64>,
    end_time: Option<f64>,
}

#[derive(Deserialize)]
struct YtInfo {
    title: Option<String>,
    duration: Option<f64>,
    chapters: Option<Vec<YtChapter>>,
}

#[derive(Deserialize)]
struct FlatEntry {
    id: Option<String>,
    title: Option<String>,
    url: Option<String>,
    duration: Option<f64>,
}

#[derive(Deserialize)]
struct FlatPlaylist {
    entries: Option<Vec<FlatEntry>>,
}

/// Fetch metadata only (no download). Fast enough to show info + routing.
pub async fn fetch_metadata(url: &str) -> Result<MediaMeta, String> {
    let out = run_capture("yt-dlp", ["-J", "--no-playlist", "--no-warnings", url]).await?;
    let info: YtInfo =
        serde_json::from_str(&out).map_err(|e| format!("cannot parse yt-dlp metadata: {e}"))?;

    let duration = info.duration.unwrap_or(0.0);
    let chapters = info
        .chapters
        .unwrap_or_default()
        .into_iter()
        .map(|c| Chapter {
            title: c.title.unwrap_or_default(),
            start: c.start_time.unwrap_or(0.0),
            end: c.end_time.unwrap_or(0.0),
        })
        .collect();

    Ok(MediaMeta {
        source_url: url.to_string(),
        title: info.title.unwrap_or_else(|| "(無題)".to_string()),
        duration_sec: duration,
        chapters,
        routing: RoutingClass::from_duration(duration),
    })
}

/// Full ingest + extract, persisting artifacts and emitting progress events.
pub async fn prepare_media(app: &AppHandle, url: &str) -> Result<Job, String> {
    let id = Uuid::new_v4().to_string();
    let work_dir = jobs_root(app)?.join(&id);
    fs::create_dir_all(&work_dir).map_err(|e| format!("cannot create work dir: {e}"))?;

    emit_progress(app, &id, "ingest", "メタデータを取得しています…");
    let meta = fetch_metadata(url).await?;

    let mut job = Job {
        id: id.clone(),
        work_dir: work_dir.to_string_lossy().into_owned(),
        stage: "metadata".to_string(),
        meta,
        artifacts: JobArtifacts::default(),
    };
    save_job(&work_dir, &job)?;

    emit_progress(app, &id, "ingest", "音声をダウンロードしています…");
    let source_audio = download_audio(url, &work_dir).await?;
    job.artifacts.source_audio = Some(source_audio.clone());
    job.stage = "ingested".to_string();
    save_job(&work_dir, &job)?;

    emit_progress(app, &id, "extract", "16kHz mono に抽出しています…");
    let wav = extract_wav(&source_audio, &work_dir).await?;
    job.artifacts.extracted_wav = Some(wav);
    job.stage = "extracted".to_string();
    save_job(&work_dir, &job)?;

    emit_progress(app, &id, "done", "音声の準備が完了しました。");
    Ok(job)
}

/// List a channel's recent uploads for the user to pick (preset click, FR-11).
pub async fn list_channel_uploads(
    channel_url: &str,
    limit: Option<u32>,
) -> Result<Vec<VideoEntry>, String> {
    let normalized = normalize_channel_url(channel_url);
    let end = limit.unwrap_or(DEFAULT_CHANNEL_LIMIT).max(1).to_string();
    let out = run_capture(
        "yt-dlp",
        [
            "-J",
            "--flat-playlist",
            "--no-warnings",
            "--playlist-end",
            end.as_str(),
            normalized.as_str(),
        ],
    )
    .await?;

    let playlist: FlatPlaylist =
        serde_json::from_str(&out).map_err(|e| format!("cannot parse channel listing: {e}"))?;

    let entries = playlist
        .entries
        .unwrap_or_default()
        .into_iter()
        .filter_map(|e| {
            let id = e.id?;
            let url = e
                .url
                .unwrap_or_else(|| format!("https://www.youtube.com/watch?v={id}"));
            Some(VideoEntry {
                id,
                title: e.title.unwrap_or_else(|| "(無題)".to_string()),
                url,
                duration_sec: e.duration,
            })
        })
        .collect();

    Ok(entries)
}

// --- internals ---

async fn download_audio(url: &str, work_dir: &Path) -> Result<String, String> {
    let out_tmpl = work_dir.join("source.%(ext)s");
    let out_tmpl_str = out_tmpl.to_string_lossy().into_owned();
    run_capture(
        "yt-dlp",
        [
            "-f",
            "bestaudio/best",
            "--no-playlist",
            "--no-warnings",
            "-o",
            out_tmpl_str.as_str(),
            url,
        ],
    )
    .await?;

    // The container extension varies (m4a/webm/opus); find the produced file.
    let produced = fs::read_dir(work_dir)
        .map_err(|e| format!("cannot read work dir: {e}"))?
        .filter_map(|e| e.ok().map(|e| e.path()))
        .find(|p| {
            p.file_stem().is_some_and(|s| s == "source")
                && p.extension().is_some_and(|x| x != "part")
        });

    produced
        .map(|p| p.to_string_lossy().into_owned())
        .ok_or_else(|| "downloaded audio file not found".to_string())
}

async fn extract_wav(source: &str, work_dir: &Path) -> Result<String, String> {
    let out = work_dir.join("audio16k.wav");
    let out_str = out.to_string_lossy().into_owned();
    run_capture(
        "ffmpeg",
        [
            "-y",
            "-i",
            source,
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            out_str.as_str(),
        ],
    )
    .await?;
    Ok(out_str)
}

/// Append `/videos` to a bare channel URL so yt-dlp lists uploads, not tabs.
fn normalize_channel_url(url: &str) -> String {
    let u = url.trim_end_matches('/');
    let is_channel =
        u.contains("/@") || u.contains("/channel/") || u.contains("/c/") || u.contains("/user/");
    let has_tab = ["/videos", "/streams", "/shorts", "/playlists", "/featured"]
        .iter()
        .any(|t| u.ends_with(t));
    if is_channel && !has_tab {
        format!("{u}/videos")
    } else {
        u.to_string()
    }
}

fn jobs_root(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("cannot resolve data dir: {e}"))?
        .join("jobs");
    fs::create_dir_all(&dir).map_err(|e| format!("cannot create jobs dir: {e}"))?;
    Ok(dir)
}

fn save_job(work_dir: &Path, job: &Job) -> Result<(), String> {
    let path = work_dir.join("job.json");
    let txt =
        serde_json::to_string_pretty(job).map_err(|e| format!("cannot serialize job: {e}"))?;
    fs::write(path, txt).map_err(|e| format!("cannot write job.json: {e}"))
}

fn emit_progress(app: &AppHandle, job_id: &str, stage: &str, message: &str) {
    let _ = app.emit(
        "linguacast://progress",
        serde_json::json!({ "job_id": job_id, "stage": stage, "message": message }),
    );
}
