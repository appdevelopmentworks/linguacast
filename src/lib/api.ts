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

export type ProgressEvent = {
  job_id: string;
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

export function listChannelUploads(channelUrl: string, limit?: number): Promise<VideoEntry[]> {
  return invoke<VideoEntry[]>("list_channel_uploads", { channelUrl, limit });
}

export function getPresets(): Promise<Presets> {
  return invoke<Presets>("get_presets");
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
