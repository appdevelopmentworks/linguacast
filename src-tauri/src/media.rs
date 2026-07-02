//! Stage 1-2 of the pipeline: ingest (yt-dlp) and extract (ffmpeg).
//!
//! From a URL we fetch metadata (title/duration/chapters), download the best
//! audio stream, and transcode to 16 kHz mono WAV (Whisper-ready). Artifacts and
//! a `job.json` are persisted under a per-job working directory so later stages
//! (STT onward, in the sidecar) can pick them up and the work is resumable.

use std::fs;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter};
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

/// Ingest an already-downloaded local audio/video file: skip yt-dlp, probe
/// duration with ffprobe, extract 16 kHz mono WAV, persist the job.
pub async fn prepare_local_media(app: &AppHandle, path: &str) -> Result<Job, String> {
    let src = Path::new(path);
    if !src.is_file() {
        return Err(format!("ファイルが見つかりません: {path}"));
    }

    let id = Uuid::new_v4().to_string();
    let work_dir = jobs_root(app)?.join(&id);
    fs::create_dir_all(&work_dir).map_err(|e| format!("cannot create work dir: {e}"))?;

    emit_progress(app, &id, "ingest", "ローカルファイルを読み込んでいます…");
    let duration = probe_duration(path).await.unwrap_or(0.0);
    let title = src
        .file_stem()
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_else(|| "(無題)".to_string());

    let meta = MediaMeta {
        source_url: path.to_string(),
        title,
        duration_sec: duration,
        chapters: Vec::new(),
        routing: RoutingClass::from_duration(duration),
    };

    let mut job = Job {
        id: id.clone(),
        work_dir: work_dir.to_string_lossy().into_owned(),
        stage: "metadata".to_string(),
        meta,
        artifacts: JobArtifacts {
            source_audio: Some(path.to_string()),
            extracted_wav: None,
        },
    };
    save_job(&work_dir, &job)?;

    emit_progress(app, &id, "extract", "16kHz mono に抽出しています…");
    let wav = extract_wav(path, &work_dir).await?;
    job.artifacts.extracted_wav = Some(wav);
    job.stage = "extracted".to_string();
    save_job(&work_dir, &job)?;

    emit_progress(app, &id, "done", "音声の準備が完了しました。");
    Ok(job)
}

async fn probe_duration(path: &str) -> Result<f64, String> {
    let out = run_capture(
        "ffprobe",
        [
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            path,
        ],
    )
    .await?;
    out.trim()
        .parse::<f64>()
        .map_err(|e| format!("cannot parse duration: {e}"))
}

/// Rough check: does this local file look audio-only (no video track to dub)?
pub fn is_audio_only_file(path: &str) -> bool {
    let ext = Path::new(path)
        .extension()
        .map(|e| e.to_string_lossy().to_lowercase())
        .unwrap_or_default();
    matches!(
        ext.as_str(),
        "mp3" | "wav" | "m4a" | "aac" | "flac" | "ogg" | "opus" | "wma"
    )
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

/// Stage artifacts detected on disk — the resume points of a job (NFR-4).
#[derive(Serialize)]
pub struct DetectedArtifacts {
    pub extracted_wav: Option<String>,
    pub source_srt: Option<String>,
    pub translated_srt: Option<String>,
    pub script_json: Option<String>,
    pub audio_wav: Option<String>,
    pub dubbed_video: Option<String>,
}

#[derive(Serialize)]
pub struct JobSummary {
    pub id: String,
    pub work_dir: String,
    pub stage: String,
    pub meta: MediaMeta,
    pub artifacts: DetectedArtifacts,
}

/// List persisted jobs (newest first) with their on-disk resume points.
pub fn list_jobs(app: &AppHandle) -> Result<Vec<JobSummary>, String> {
    let root = jobs_root(app)?;
    let mut jobs: Vec<(std::time::SystemTime, JobSummary)> = Vec::new();

    for entry in fs::read_dir(&root).map_err(|e| format!("cannot read jobs dir: {e}"))? {
        let Ok(entry) = entry else { continue };
        let dir = entry.path();
        let job_file = dir.join("job.json");
        let Ok(txt) = fs::read_to_string(&job_file) else {
            continue;
        };
        let Ok(job) = serde_json::from_str::<Job>(&txt) else {
            continue;
        };
        let mtime = fs::metadata(&job_file)
            .and_then(|m| m.modified())
            .unwrap_or(std::time::SystemTime::UNIX_EPOCH);

        let detect = |name: &str| -> Option<String> {
            let p = dir.join(name);
            p.is_file().then(|| p.to_string_lossy().into_owned())
        };

        jobs.push((
            mtime,
            JobSummary {
                id: job.id,
                work_dir: job.work_dir,
                stage: job.stage,
                meta: job.meta,
                artifacts: DetectedArtifacts {
                    extracted_wav: detect("audio16k.wav"),
                    source_srt: detect("source.srt"),
                    translated_srt: detect("translated.ja.srt"),
                    script_json: detect("script.json"),
                    audio_wav: detect("audio.ja.wav"),
                    dubbed_video: detect("dubbed.mp4"),
                },
            },
        ));
    }

    jobs.sort_by_key(|(t, _)| std::cmp::Reverse(*t));
    Ok(jobs.into_iter().take(10).map(|(_, j)| j).collect())
}

/// Download the full video (merged mp4) for dub mode. Cached per job dir.
pub async fn download_video(work_dir: &str, url: &str) -> Result<String, String> {
    let dir = Path::new(work_dir);
    let existing = dir.join("video.mp4");
    if existing.exists() {
        return Ok(existing.to_string_lossy().into_owned());
    }

    let out_tmpl = dir.join("video.%(ext)s");
    let out_tmpl_str = out_tmpl.to_string_lossy().into_owned();
    run_capture(
        "yt-dlp",
        [
            // Cap at 1080p to keep dub-mode downloads sane.
            "-f",
            "bv*[height<=1080]+ba/b[height<=1080]/b",
            "--merge-output-format",
            "mp4",
            "--no-playlist",
            "--no-warnings",
            "-o",
            out_tmpl_str.as_str(),
            url,
        ],
    )
    .await?;

    if existing.exists() {
        Ok(existing.to_string_lossy().into_owned())
    } else {
        Err("downloaded video file not found".to_string())
    }
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
    let dir = crate::config::data_root(app)?.join("jobs");
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
