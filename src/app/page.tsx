"use client";

import { useCallback, useEffect, useState } from "react";
import {
  checkDependencies,
  fetchMetadata,
  getPresets,
  getSettings,
  listChannelUploads,
  onProgress,
  pingSidecar,
  prepareMedia,
  saveSettings,
  tierLabel,
  transcribe,
  translateBackends,
  translateSrt,
  formatDuration,
  routingLabel,
  type DependencyReport,
  type Job,
  type MediaMeta,
  type Presets,
  type Settings,
  type SidecarHealth,
  type TranscribeResult,
  type TranslateBackends,
  type TranslateSrtResult,
  type VideoEntry,
} from "@/lib/api";

type TranslationMode = "full" | "summary";
type DeliveryMode = "subs" | "dub";

export default function Home() {
  const [deps, setDeps] = useState<DependencyReport | null>(null);
  const [presets, setPresets] = useState<Presets>([]);
  const [health, setHealth] = useState<SidecarHealth | null>(null);

  const [url, setUrl] = useState("");
  const [translationMode, setTranslationMode] = useState<TranslationMode>("full");
  const [deliveryMode, setDeliveryMode] = useState<DeliveryMode>("subs");

  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<MediaMeta | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [transcript, setTranscript] = useState<TranscribeResult | null>(null);
  const [translation, setTranslation] = useState<TranslateSrtResult | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [backends, setBackends] = useState<TranslateBackends | null>(null);

  const [openChannel, setOpenChannel] = useState<string | null>(null);
  const [uploads, setUploads] = useState<VideoEntry[]>([]);
  const [uploadsLoading, setUploadsLoading] = useState(false);

  // Initial load: dependency check, presets, sidecar health, settings, LLM tiers.
  useEffect(() => {
    const init = async () => {
      const [d, p, h, s, b] = await Promise.allSettled([
        checkDependencies(),
        getPresets(),
        pingSidecar(),
        getSettings(),
        translateBackends(),
      ]);
      if (d.status === "fulfilled") setDeps(d.value);
      if (p.status === "fulfilled") setPresets(p.value);
      if (h.status === "fulfilled") setHealth(h.value);
      if (s.status === "fulfilled") setSettings(s.value);
      if (b.status === "fulfilled") setBackends(b.value);
    };
    void init();
  }, []);

  const changeModel = useCallback(
    (model: string) => {
      if (!settings) return;
      const next = { ...settings, translation_model: model };
      setSettings(next);
      void saveSettings(next);
    },
    [settings],
  );

  // Local model choices from both local tiers (Ollama first, then LM Studio).
  const modelChoices = (() => {
    const list: string[] = [];
    for (const m of backends?.ollama.models ?? []) list.push(m);
    for (const m of backends?.lmstudio.models ?? []) if (!list.includes(m)) list.push(m);
    const current = settings?.translation_model;
    if (current && !list.includes(current)) list.unshift(current);
    return list;
  })();

  // Subscribe to pipeline progress events (setState in an external callback).
  useEffect(() => {
    let unlisten: (() => void) | undefined;
    void onProgress((e) => setProgress(e.message)).then((u) => {
      unlisten = u;
    });
    return () => unlisten?.();
  }, []);

  const canStart = url.trim().length > 0 && !busy;

  const runPrepare = useCallback(async () => {
    setBusy(true);
    setError(null);
    setJob(null);
    setPreview(null);
    setTranscript(null);
    setTranslation(null);
    setProgress("開始しています…");
    try {
      setJob(await prepareMedia(url.trim()));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
      setProgress(null);
    }
  }, [url]);

  const runTranscribe = useCallback(async () => {
    if (!job?.artifacts.extracted_wav) return;
    setBusy(true);
    setError(null);
    setTranscript(null);
    setTranslation(null);
    setProgress("文字起こしを開始しています…");
    try {
      setTranscript(await transcribe(job.artifacts.extracted_wav, job.work_dir));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
      setProgress(null);
    }
  }, [job]);

  const runTranslate = useCallback(async () => {
    if (!job || !transcript?.srt_path) return;
    setBusy(true);
    setError(null);
    setTranslation(null);
    setProgress("和訳を開始しています…");
    try {
      setTranslation(await translateSrt(transcript.srt_path, job.work_dir));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
      setProgress(null);
    }
  }, [job, transcript]);

  const runPreview = useCallback(async () => {
    setBusy(true);
    setError(null);
    setPreview(null);
    try {
      setPreview(await fetchMetadata(url.trim()));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }, [url]);

  const toggleChannel = useCallback(
    async (channelUrl: string) => {
      if (openChannel === channelUrl) {
        setOpenChannel(null);
        setUploads([]);
        return;
      }
      setOpenChannel(channelUrl);
      setUploads([]);
      setUploadsLoading(true);
      setError(null);
      try {
        setUploads(await listChannelUploads(channelUrl));
      } catch (e) {
        setError(String(e));
      } finally {
        setUploadsLoading(false);
      }
    },
    [openChannel],
  );

  const pickVideo = useCallback((v: VideoEntry) => {
    setUrl(v.url);
    setOpenChannel(null);
    setUploads([]);
  }, []);

  const sidecarOk = health?.reachable ?? false;
  const depsMissing = deps ? deps.tools.filter((t) => !t.available) : [];

  return (
    <main className="container">
      <header className="app-header">
        <h1>linguacast</h1>
        <span className="tagline">外国語の一次情報を、日本語の音声で。</span>
      </header>

      {depsMissing.length > 0 && (
        <section className="banner banner-warn" role="alert">
          <strong>必要なツールが見つかりません</strong>
          <ul>
            {depsMissing.map((t) => (
              <li key={t.name}>{t.hint ?? `${t.name} が見つかりません。`}</li>
            ))}
          </ul>
        </section>
      )}

      {/* URL input + output modes + start */}
      <section className="input-card">
        <input
          className="url-input"
          type="url"
          inputMode="url"
          placeholder="🔗 YouTube などの URL を入力"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && canStart) void runPrepare();
          }}
          disabled={busy}
        />

        <div className="controls-row">
          <div className="segmented" role="group" aria-label="出力">
            <button
              className={translationMode === "full" ? "seg active" : "seg"}
              onClick={() => setTranslationMode("full")}
              disabled={busy}
            >
              全訳
            </button>
            <button
              className={translationMode === "summary" ? "seg active" : "seg"}
              onClick={() => setTranslationMode("summary")}
              disabled={busy}
            >
              要約
            </button>
          </div>

          <div className="segmented" role="group" aria-label="形式">
            <button
              className={deliveryMode === "subs" ? "seg active" : "seg"}
              onClick={() => setDeliveryMode("subs")}
              disabled={busy}
            >
              字幕のみ
            </button>
            <button
              className={deliveryMode === "dub" ? "seg active" : "seg"}
              onClick={() => setDeliveryMode("dub")}
              disabled={busy}
            >
              吹き替え
            </button>
          </div>

          <button className="start-btn" onClick={() => void runPrepare()} disabled={!canStart}>
            ▶ 開始
          </button>
        </div>

        <div className="secondary-row">
          <button
            className="link-btn"
            onClick={() => void runPreview()}
            disabled={!canStart}
            title="ダウンロードせずにメタ情報だけ取得します"
          >
            メタ情報のみ取得
          </button>
          <span className="mode-note">
            ※ 出力モードは後続の翻訳・合成段階で使用します（Session 3 以降）。
          </span>
        </div>
      </section>

      {busy && progress && (
        <section className="banner banner-info">
          <span className="spinner" aria-hidden /> {progress}
        </section>
      )}

      {error && (
        <section className="banner banner-error" role="alert">
          {error}
        </section>
      )}

      {preview && !job && <MediaCard meta={preview} title="メタ情報" />}

      {job && (
        <>
          <MediaCard meta={job.meta} title="音声準備 完了" />
          <section className="artifact-card">
            <div className="artifact-row">
              <span className="artifact-label">ジョブ ID</span>
              <code>{job.id}</code>
            </div>
            <div className="artifact-row">
              <span className="artifact-label">作業フォルダ</span>
              <code className="path">{job.work_dir}</code>
            </div>
            {job.artifacts.extracted_wav && (
              <div className="artifact-row">
                <span className="artifact-label">抽出音声 (16kHz mono)</span>
                <code className="path">{job.artifacts.extracted_wav}</code>
              </div>
            )}
            <div className="artifact-row">
              <span className="artifact-label">次のステップ</span>
              <button
                className="start-btn"
                onClick={() => void runTranscribe()}
                disabled={busy || !job.artifacts.extracted_wav}
              >
                文字起こし (Whisper)
              </button>
            </div>
          </section>
        </>
      )}

      {transcript && (
        <section className="media-card">
          <div className="media-card-head">
            <span className="section-label">文字起こし 完了（原語 SRT）</span>
            <span className="routing-badge routing-medium">
              {transcript.backend} / {transcript.device}
            </span>
          </div>
          <div className="media-meta">
            <span>言語: {transcript.language}</span>
            <span>セグメント: {transcript.segment_count}</span>
            <span>モデル: {transcript.model}</span>
          </div>
          {transcript.srt_path && (
            <div className="artifact-row">
              <span className="artifact-label">SRT</span>
              <code className="path">{transcript.srt_path}</code>
            </div>
          )}
          <div className="transcript-preview">
            {transcript.segments.slice(0, 5).map((s, i) => (
              <div className="transcript-line" key={i}>
                <span className="transcript-time">{formatDuration(s.start)}</span>
                <span>{s.text}</span>
              </div>
            ))}
            {transcript.segments.length > 5 && (
              <div className="transcript-more">
                … 他 {transcript.segments.length - 5} セグメント
              </div>
            )}
          </div>
          <div className="artifact-row">
            <span className="artifact-label">翻訳モデル</span>
            <select
              className="model-select"
              value={settings?.translation_model ?? ""}
              onChange={(e) => changeModel(e.target.value)}
              disabled={busy}
            >
              {modelChoices.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
            <button
              className="start-btn"
              onClick={() => void runTranslate()}
              disabled={busy || !transcript.srt_path}
            >
              和訳 (SRT)
            </button>
          </div>
        </section>
      )}

      {translation && (
        <section className="media-card">
          <div className="media-card-head">
            <span className="section-label">和訳 完了（日本語 SRT）</span>
            <span className="routing-badge routing-short">
              {tierLabel(translation.tier)} / {translation.model}
            </span>
          </div>
          <div className="media-meta">
            <span>セグメント: {translation.segment_count}</span>
          </div>
          <div className="artifact-row">
            <span className="artifact-label">和訳 SRT</span>
            <code className="path">{translation.translated_srt_path}</code>
          </div>
          <div className="transcript-preview">
            {translation.samples.map((s, i) => (
              <div className="translate-pair" key={i}>
                <div className="transcript-line">
                  <span className="transcript-time">{formatDuration(s.start)}</span>
                  <span className="src-text">{s.src}</span>
                </div>
                <div className="transcript-line">
                  <span className="transcript-time" />
                  <span>{s.dst}</span>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Preset channels */}
      <section className="presets">
        <div className="section-label">プリセットチャンネル</div>
        {presets.map((cat) => (
          <div className="preset-category" key={cat.category}>
            <div className="category-heading">{cat.category}</div>
            {cat.channels.map((ch) => (
              <div key={ch.url}>
                <button
                  className="channel-btn"
                  onClick={() => void toggleChannel(ch.url)}
                  disabled={busy}
                >
                  <span className="caret">{openChannel === ch.url ? "▼" : "▶"}</span> {ch.label}
                </button>
                {openChannel === ch.url && (
                  <div className="uploads">
                    {uploadsLoading && <div className="uploads-loading">直近の動画を取得中…</div>}
                    {!uploadsLoading && uploads.length === 0 && (
                      <div className="uploads-loading">動画が見つかりませんでした。</div>
                    )}
                    {uploads.map((v) => (
                      <button className="upload-item" key={v.id} onClick={() => pickVideo(v)}>
                        <span className="upload-title">{v.title}</span>
                        {v.duration_sec != null && (
                          <span className="upload-dur">{formatDuration(v.duration_sec)}</span>
                        )}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        ))}
      </section>

      <footer className="status-bar">
        <span className={`status-dot ${sidecarOk ? "ok" : "ng"}`} aria-hidden />
        <span>
          {sidecarOk
            ? `サイドカー接続OK（${health?.service ?? "sidecar"} v${health?.version ?? "?"}）`
            : "サイドカー未接続"}
        </span>
      </footer>
    </main>
  );
}

function MediaCard({ meta, title }: { meta: MediaMeta; title: string }) {
  return (
    <section className="media-card">
      <div className="media-card-head">
        <span className="section-label">{title}</span>
        <span className={`routing-badge routing-${meta.routing}`}>
          {routingLabel(meta.routing)}
        </span>
      </div>
      <div className="media-title">{meta.title}</div>
      <div className="media-meta">
        <span>長さ: {formatDuration(meta.duration_sec)}</span>
        <span>チャプター: {meta.chapters.length} 個</span>
      </div>
    </section>
  );
}
