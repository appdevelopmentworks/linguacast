// Typed wrappers around the Rust Tauri commands. The UI talks only to Rust;
// Rust proxies to the sidecar and orchestrates yt-dlp / ffmpeg.

import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

export type SidecarHealth = {
  reachable: boolean;
  status: string | null;
  service: string | null;
  version: string | null;
  detail: string | null;
};

export type ToolStatus = {
  name: string;
  available: boolean;
  version: string | null;
  hint: string | null;
};

export type DependencyReport = {
  tools: ToolStatus[];
  all_ok: boolean;
};

export type RoutingClass = "short" | "medium" | "long";

export type Chapter = { title: string; start: number; end: number };

export type MediaMeta = {
  source_url: string;
  title: string;
  duration_sec: number;
  chapters: Chapter[];
  routing: RoutingClass;
};

export type JobArtifacts = {
  source_audio: string | null;
  extracted_wav: string | null;
};

export type Job = {
  id: string;
  work_dir: string;
  stage: string;
  meta: MediaMeta;
  artifacts: JobArtifacts;
};

export type VideoEntry = {
  id: string;
  title: string;
  url: string;
  duration_sec: number | null;
};

export type PresetChannel = { label: string; url: string };
export type PresetCategory = { category: string; channels: PresetChannel[] };
export type Presets = PresetCategory[];

export type SttSegment = { start: number; end: number; text: string };

export type TranscribeResult = {
  language: string;
  duration: number;
  backend: string;
  device: string;
  model: string;
  segment_count: number;
  srt_path: string | null;
  segments: SttSegment[];
};

export type Settings = {
  translation_model: string;
  openrouter_model: string | null;
  source_lang: string;
  narrator_voice: number;
  guest_voice: number;
};

export type TierInfo = { available: boolean; models: string[] };
export type TranslateBackends = { ollama: TierInfo; lmstudio: TierInfo };

export type TranslateSample = { start: number; end: number; src: string; dst: string };

export type TranslateSrtResult = {
  tier: string;
  model: string;
  base_url: string;
  segment_count: number;
  translated_srt_path: string;
  samples: TranslateSample[];
};

export type ScriptLine = { speaker: string; text: string };

export type SummarizeResult = {
  tier: string;
  model: string;
  title: string;
  format: "narration" | "dialogue";
  strategy: "single_pass" | "hierarchical";
  section_count: number;
  line_count: number;
  script_txt_path: string;
  script_json_path: string;
  lines: ScriptLine[];
};

export type SpeakerStyle = { id: number; name: string };
export type SpeakerInfo = { name: string; styles: SpeakerStyle[] };

export type TtsStatus = {
  voicevox_available: boolean;
  voicevox_version: string | null;
  speakers: SpeakerInfo[];
  warning: string | null;
};

export type SynthesizeResult = {
  engine: string;
  audio_path: string;
  line_count: number;
};

export type SegmentFit = {
  index: number;
  start_sec: number;
  slot_sec: number;
  natural_sec: number;
  final_sec: number;
  method: string;
  shortened: boolean;
};

export type DubResult = {
  dubbed_audio_path: string;
  dubbed_video_path: string | null;
  segment_count: number;
  fit_summary: Record<string, number>;
  fits: SegmentFit[];
};

export type DetectedArtifacts = {
  extracted_wav: string | null;
  source_srt: string | null;
  translated_srt: string | null;
  script_json: string | null;
  audio_wav: string | null;
  dubbed_video: string | null;
};

export type JobSummary = {
  id: string;
  work_dir: string;
  stage: string;
  meta: MediaMeta;
  artifacts: DetectedArtifacts;
};

export type ShareInfo = {
  url: string;
  filename: string;
  lan_ip: string;
  port: number;
  expires_min: number;
};

export type ProgressEvent = {
  job_id?: string;
  stage: string;
  message: string;
};

export function pingSidecar(): Promise<SidecarHealth> {
  return invoke<SidecarHealth>("ping_sidecar");
}

export function checkDependencies(): Promise<DependencyReport> {
  return invoke<DependencyReport>("check_dependencies");
}

export function fetchMetadata(url: string): Promise<MediaMeta> {
  return invoke<MediaMeta>("fetch_metadata", { url });
}

export function prepareMedia(url: string): Promise<Job> {
  return invoke<Job>("prepare_media", { url });
}

export function prepareLocalMedia(path: string): Promise<Job> {
  return invoke<Job>("prepare_local_media", { path });
}

export function listJobs(): Promise<JobSummary[]> {
  return invoke<JobSummary[]>("list_jobs");
}

export function setOpenrouterKey(key: string): Promise<void> {
  return invoke("set_openrouter_key", { key });
}

export function hasOpenrouterKey(): Promise<boolean> {
  return invoke<boolean>("has_openrouter_key");
}

export function setGoogleTtsKey(key: string): Promise<void> {
  return invoke("set_google_tts_key", { key });
}

export function hasGoogleTtsKey(): Promise<boolean> {
  return invoke<boolean>("has_google_tts_key");
}

export function listChannelUploads(channelUrl: string, limit?: number): Promise<VideoEntry[]> {
  return invoke<VideoEntry[]>("list_channel_uploads", { channelUrl, limit });
}

export function transcribe(
  audioPath: string,
  outputDir: string,
  modelSize?: string,
): Promise<TranscribeResult> {
  return invoke<TranscribeResult>("transcribe", { audioPath, outputDir, modelSize });
}

export function getPresets(): Promise<Presets> {
  return invoke<Presets>("get_presets");
}

export function getSettings(): Promise<Settings> {
  return invoke<Settings>("get_settings");
}

export function saveSettings(settings: Settings): Promise<void> {
  return invoke("save_settings", { settings });
}

export function translateBackends(): Promise<TranslateBackends> {
  return invoke<TranslateBackends>("translate_backends");
}

export function translateSrt(
  srtPath: string,
  outputDir: string,
  model?: string,
): Promise<TranslateSrtResult> {
  return invoke<TranslateSrtResult>("translate_srt", { srtPath, outputDir, model });
}

export function summarizeScript(
  srtPath: string,
  outputDir: string,
  sourceTitle?: string,
  chapters?: Chapter[],
): Promise<SummarizeResult> {
  return invoke<SummarizeResult>("summarize_script", {
    srtPath,
    outputDir,
    sourceTitle,
    chapters,
  });
}

export function ttsStatus(): Promise<TtsStatus> {
  return invoke<TtsStatus>("tts_status");
}

export function synthesizeScript(
  scriptJsonPath: string,
  outputDir: string,
): Promise<SynthesizeResult> {
  return invoke<SynthesizeResult>("synthesize_script", { scriptJsonPath, outputDir });
}

export function dubVideo(
  translatedSrtPath: string,
  workDir: string,
  sourceUrl: string,
): Promise<DubResult> {
  return invoke<DubResult>("dub_video", { translatedSrtPath, workDir, sourceUrl });
}

export function shareFile(path: string): Promise<ShareInfo> {
  return invoke<ShareInfo>("share_file", { path });
}

export const FIT_METHOD_LABELS: Record<string, string> = {
  natural: "そのまま",
  shortened: "短縮訳",
  absorbed: "無音吸収",
  speed_scaled: "話速調整",
  stretched: "タイムストレッチ",
  trimmed: "トリム",
};

const TIER_LABELS: Record<string, string> = {
  ollama: "ローカル (Ollama)",
  lmstudio: "ローカル (LM Studio)",
  openrouter: "クラウド (OpenRouter)",
};

export function tierLabel(tier: string): string {
  return TIER_LABELS[tier] ?? tier;
}

export function savePresets(presets: Presets): Promise<void> {
  return invoke("save_presets", { presets });
}

export function onProgress(cb: (e: ProgressEvent) => void): Promise<UnlistenFn> {
  return listen<ProgressEvent>("linguacast://progress", (event) => cb(event.payload));
}

/** Format seconds as H:MM:SS (or M:SS under an hour). */
export function formatDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.round(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const pad = (n: number) => n.toString().padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
}

const ROUTING_LABELS: Record<RoutingClass, string> = {
  short: "短編",
  medium: "中編",
  long: "長編",
};

export function routingLabel(routing: RoutingClass): string {
  return ROUTING_LABELS[routing];
}
