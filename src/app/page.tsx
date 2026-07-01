"use client";

import { useCallback, useEffect, useState } from "react";
import {
  checkDependencies,
  fetchMetadata,
  getPresets,
  listChannelUploads,
  onProgress,
  pingSidecar,
  prepareMedia,
  formatDuration,
  routingLabel,
  type DependencyReport,
  type Job,
  type MediaMeta,
  type Presets,
  type SidecarHealth,
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

  const [openChannel, setOpenChannel] = useState<string | null>(null);
  const [uploads, setUploads] = useState<VideoEntry[]>([]);
  const [uploadsLoading, setUploadsLoading] = useState(false);

  // Initial load: dependency check, presets, sidecar health.
  useEffect(() => {
    const init = async () => {
      const [d, p, h] = await Promise.allSettled([
        checkDependencies(),
        getPresets(),
        pingSidecar(),
      ]);
      if (d.status === "fulfilled") setDeps(d.value);
      if (p.status === "fulfilled") setPresets(p.value);
      if (h.status === "fulfilled") setHealth(h.value);
    };
    void init();
  }, []);

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
          </section>
        </>
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
