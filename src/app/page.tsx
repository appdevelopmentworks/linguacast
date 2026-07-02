"use client";

import { useCallback, useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { open as openFileDialog } from "@tauri-apps/plugin-dialog";
import {
  checkDependencies,
  dubVideo,
  edgeVoices,
  fetchMetadata,
  FIT_METHOD_LABELS,
  getPresets,
  getSettings,
  hasGoogleTtsKey,
  hasOpenrouterKey,
  listChannelUploads,
  listJobs,
  onProgress,
  openrouterModels,
  openWorkDir,
  pingSidecar,
  prepareLocalMedia,
  prepareMedia,
  savePresets,
  saveSettings,
  setGoogleTtsKey,
  setOpenrouterKey,
  shareFile,
  summarizeScript,
  synthesizeScript,
  tierLabel,
  transcribe,
  translateBackends,
  translateSrt,
  TTS_ENGINE_LABELS,
  ttsStatus,
  formatDuration,
  routingLabel,
  type DependencyReport,
  type DubResult,
  type EdgeVoice,
  type Job,
  type JobSummary,
  type MediaMeta,
  type OpenRouterModel,
  type Presets,
  type Settings,
  type ShareInfo,
  type SidecarHealth,
  type SummarizeResult,
  type SynthesizeResult,
  type TranscribeResult,
  type TranslateBackends,
  type TranslateSrtResult,
  type TtsStatus,
  type VideoEntry,
} from "@/lib/api";

type TranslationMode = "full" | "summary";
type DeliveryMode = "subs" | "dub";

const MEDIA_EXTENSIONS = [
  "mp4",
  "mkv",
  "webm",
  "mov",
  "avi",
  "mp3",
  "wav",
  "m4a",
  "aac",
  "flac",
  "ogg",
  "opus",
];

export default function Home() {
  const [deps, setDeps] = useState<DependencyReport | null>(null);
  const [presets, setPresets] = useState<Presets>([]);
  const [health, setHealth] = useState<SidecarHealth | null>(null);

  const [url, setUrl] = useState("");
  // Defaults per user choice: full translation, dubbed video.
  const [translationMode, setTranslationMode] = useState<TranslationMode>("full");
  const [deliveryMode, setDeliveryMode] = useState<DeliveryMode>("dub");

  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const [progressPercent, setProgressPercent] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<MediaMeta | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [transcript, setTranscript] = useState<TranscribeResult | null>(null);
  const [translation, setTranslation] = useState<TranslateSrtResult | null>(null);
  const [script, setScript] = useState<SummarizeResult | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [backends, setBackends] = useState<TranslateBackends | null>(null);
  const [tts, setTts] = useState<TtsStatus | null>(null);
  const [audio, setAudio] = useState<SynthesizeResult | null>(null);
  const [dub, setDub] = useState<DubResult | null>(null);
  const [share, setShare] = useState<ShareInfo | null>(null);

  const [openChannel, setOpenChannel] = useState<string | null>(null);
  const [uploads, setUploads] = useState<VideoEntry[]>([]);
  const [uploadsLoading, setUploadsLoading] = useState(false);

  const [showSettings, setShowSettings] = useState(false);
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [resume, setResume] = useState<JobSummary | null>(null);
  const [orKeySet, setOrKeySet] = useState(false);
  const [googleKeySet, setGoogleKeySet] = useState(false);
  const [orKeyInput, setOrKeyInput] = useState("");
  const [googleKeyInput, setGoogleKeyInput] = useState("");
  const [newPreset, setNewPreset] = useState({ category: "", label: "", url: "" });
  const [dragActive, setDragActive] = useState(false);
  const [orModels, setOrModels] = useState<OpenRouterModel[]>([]);
  const [edgeVoiceList, setEdgeVoiceList] = useState<EdgeVoice[]>([]);

  // Initial load: dependency check, presets, sidecar health, settings, LLM tiers.
  useEffect(() => {
    const init = async () => {
      const [d, p, h, s, b, t, j, ok, gk] = await Promise.allSettled([
        checkDependencies(),
        getPresets(),
        pingSidecar(),
        getSettings(),
        translateBackends(),
        ttsStatus(),
        listJobs(),
        hasOpenrouterKey(),
        hasGoogleTtsKey(),
      ]);
      if (d.status === "fulfilled") setDeps(d.value);
      if (p.status === "fulfilled") setPresets(p.value);
      if (h.status === "fulfilled") setHealth(h.value);
      if (s.status === "fulfilled") setSettings(s.value);
      if (b.status === "fulfilled") setBackends(b.value);
      if (t.status === "fulfilled") setTts(t.value);
      if (j.status === "fulfilled") setJobs(j.value);
      if (ok.status === "fulfilled") setOrKeySet(ok.value);
      if (gk.status === "fulfilled") setGoogleKeySet(gk.value);
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

  const changeVoice = useCallback(
    (role: "narrator_voice" | "guest_voice", styleId: number) => {
      if (!settings) return;
      const next = { ...settings, [role]: styleId };
      setSettings(next);
      void saveSettings(next);
    },
    [settings],
  );

  const runSynthesize = useCallback(
    async (scriptJsonPath?: string) => {
      const path = scriptJsonPath ?? script?.script_json_path;
      if (!job || !path) return;
      setBusy(true);
      setError(null);
      setAudio(null);
      setProgress("音声合成を開始しています…");
      try {
        setAudio(await synthesizeScript(path, job.work_dir));
      } catch (e) {
        setError(String(e));
      } finally {
        setBusy(false);
        setProgress(null);
      }
    },
    [job, script],
  );

  const runDub = useCallback(
    async (translatedSrtPath?: string) => {
      const srt = translatedSrtPath ?? translation?.translated_srt_path;
      if (!job || !srt) return;
      setBusy(true);
      setError(null);
      setDub(null);
      setProgress("吹き替え生成を開始しています…");
      try {
        setDub(await dubVideo(srt, job.work_dir, job.meta.source_url));
      } catch (e) {
        setError(String(e));
      } finally {
        setBusy(false);
        setProgress(null);
      }
    },
    [job, translation],
  );

  // Flattened VOICEVOX style choices: 「話者名（スタイル）」 -> style id.
  const voiceChoices = (tts?.speakers ?? []).flatMap((sp) =>
    sp.styles.map((st) => ({ id: st.id, label: `${sp.name}（${st.name}）` })),
  );

  const runShare = useCallback(async (path: string) => {
    setError(null);
    setShare(null);
    try {
      setShare(await shareFile(path));
    } catch (e) {
      setError(String(e));
    }
  }, []);

  const resetPipeline = useCallback(() => {
    setJob(null);
    setPreview(null);
    setTranscript(null);
    setTranslation(null);
    setScript(null);
    setAudio(null);
    setDub(null);
    setShare(null);
    setResume(null);
  }, []);

  const handleLocalFile = useCallback(
    async (path: string) => {
      if (busy) return;
      const ext = path.split(".").pop()?.toLowerCase() ?? "";
      if (!MEDIA_EXTENSIONS.includes(ext)) {
        setError(`対応していないファイル形式です: .${ext}（対応: ${MEDIA_EXTENSIONS.join(", ")}）`);
        return;
      }
      setBusy(true);
      setError(null);
      resetPipeline();
      setProgress("ローカルファイルを取り込んでいます…");
      try {
        setJob(await prepareLocalMedia(path));
      } catch (e) {
        setError(String(e));
      } finally {
        setBusy(false);
        setProgress(null);
      }
    },
    [busy, resetPipeline],
  );

  const runOpenLocal = useCallback(async () => {
    const picked = await openFileDialog({
      multiple: false,
      title: "音声・動画ファイルを選択",
      filters: [{ name: "メディアファイル", extensions: MEDIA_EXTENSIONS }],
    });
    if (typeof picked !== "string") return;
    await handleLocalFile(picked);
  }, [handleLocalFile]);

  // Native drag & drop from the OS (Tauri drag-drop carries real file paths;
  // HTML5 drop events inside a webview do not).
  useEffect(() => {
    let unlisten: (() => void) | undefined;
    void getCurrentWebview()
      .onDragDropEvent((event) => {
        const t = event.payload.type;
        if (t === "enter" || t === "over") {
          setDragActive(true);
        } else if (t === "leave") {
          setDragActive(false);
        } else if (t === "drop") {
          setDragActive(false);
          const paths = event.payload.paths;
          if (paths && paths.length > 0) void handleLocalFile(paths[0]);
        }
      })
      .then((u) => {
        unlisten = u;
      });
    return () => unlisten?.();
  }, [handleLocalFile]);

  const resumeJob = useCallback(
    (summary: JobSummary) => {
      resetPipeline();
      setResume(summary);
      setJob({
        id: summary.id,
        work_dir: summary.work_dir,
        stage: summary.stage,
        meta: summary.meta,
        artifacts: {
          source_audio: null,
          extracted_wav: summary.artifacts.extracted_wav,
        },
      });
    },
    [resetPipeline],
  );

  // --- settings panel operations ---

  const saveOrKey = useCallback(async () => {
    try {
      await setOpenrouterKey(orKeyInput.trim());
      setOrKeyInput("");
      setOrKeySet(await hasOpenrouterKey());
    } catch (e) {
      setError(String(e));
    }
  }, [orKeyInput]);

  const saveGoogleKey = useCallback(async () => {
    try {
      await setGoogleTtsKey(googleKeyInput.trim());
      setGoogleKeyInput("");
      setGoogleKeySet(await hasGoogleTtsKey());
    } catch (e) {
      setError(String(e));
    }
  }, [googleKeyInput]);

  const changeSetting = useCallback(
    (patch: Partial<Settings>) => {
      if (!settings) return;
      const next = { ...settings, ...patch };
      setSettings(next);
      void saveSettings(next);
    },
    [settings],
  );

  const updatePresets = useCallback((next: Presets) => {
    setPresets(next);
    void savePresets(next);
  }, []);

  const movePreset = useCallback(
    (catIdx: number, chIdx: number, dir: -1 | 1) => {
      const next = presets.map((c) => ({ ...c, channels: [...c.channels] }));
      const channels = next[catIdx].channels;
      const target = chIdx + dir;
      if (target < 0 || target >= channels.length) return;
      [channels[chIdx], channels[target]] = [channels[target], channels[chIdx]];
      updatePresets(next);
    },
    [presets, updatePresets],
  );

  const removePreset = useCallback(
    (catIdx: number, chIdx: number) => {
      const next = presets.map((c) => ({ ...c, channels: [...c.channels] }));
      next[catIdx].channels.splice(chIdx, 1);
      updatePresets(next.filter((c) => c.channels.length > 0));
    },
    [presets, updatePresets],
  );

  const addPreset = useCallback(() => {
    const category = newPreset.category.trim();
    const label = newPreset.label.trim();
    const presetUrl = newPreset.url.trim();
    if (!category || !label || !presetUrl) return;
    const next = presets.map((c) => ({ ...c, channels: [...c.channels] }));
    const existing = next.find((c) => c.category === category);
    if (existing) {
      existing.channels.push({ label, url: presetUrl });
    } else {
      next.push({ category, channels: [{ label, url: presetUrl }] });
    }
    updatePresets(next);
    setNewPreset({ category: "", label: "", url: "" });
  }, [newPreset, presets, updatePresets]);

  // Local model choices from both local tiers (Ollama first, then LM Studio).
  const modelChoices = (() => {
    const list: string[] = [];
    for (const m of backends?.ollama.models ?? []) list.push(m);
    for (const m of backends?.lmstudio.models ?? []) if (!list.includes(m)) list.push(m);
    const current = settings?.translation_model;
    if (current && !list.includes(current)) list.unshift(current);
    return list;
  })();

  // Fetch the OpenRouter catalogue once, when the settings panel first opens.
  useEffect(() => {
    if (!showSettings || orModels.length > 0) return;
    void openrouterModels()
      .then(setOrModels)
      .catch(() => {});
  }, [showSettings, orModels.length]);

  // Fetch Edge TTS voices once, when the settings panel first opens.
  useEffect(() => {
    if (!showSettings || edgeVoiceList.length > 0) return;
    void edgeVoices()
      .then(setEdgeVoiceList)
      .catch(() => {});
  }, [showSettings, edgeVoiceList.length]);

  // Periodic engine health refresh for the header indicators (LLM / VOICEVOX).
  useEffect(() => {
    const timer = setInterval(() => {
      void translateBackends()
        .then(setBackends)
        .catch(() => {});
      void ttsStatus()
        .then(setTts)
        .catch(() => {});
    }, 20000);
    return () => clearInterval(timer);
  }, []);

  // Subscribe to pipeline progress events (setState in an external callback).
  useEffect(() => {
    let unlisten: (() => void) | undefined;
    void onProgress((e) => {
      setProgress(e.message);
      setProgressPercent(e.percent ?? null);
    }).then((u) => {
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
    setScript(null);
    setAudio(null);
    setDub(null);
    setShare(null);
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

  // One-click pipeline: follows the output-mode toggles to the end.
  // 全訳+吹き替え -> dub video / 全訳+字幕のみ -> translated SRT /
  // 要約 -> podcast script + audio. Pass a Job to skip the fetch stage.
  const runPipeline = useCallback(
    async (fromJob?: Job) => {
      setBusy(true);
      setError(null);
      if (!fromJob) resetPipeline();
      setPreview(null);
      setTranscript(null);
      setTranslation(null);
      setScript(null);
      setAudio(null);
      setDub(null);
      setShare(null);
      try {
        let j = fromJob ?? null;
        if (!j) {
          setProgress("メディアを取得しています…");
          j = await prepareMedia(url.trim());
          setJob(j);
        }
        if (!j.artifacts.extracted_wav) {
          throw new Error("抽出済み音声が見つかりません。");
        }

        const t = await transcribe(j.artifacts.extracted_wav, j.work_dir);
        setTranscript(t);
        if (!t.srt_path) throw new Error("原語 SRT の生成に失敗しました。");

        if (translationMode === "full") {
          const tr = await translateSrt(t.srt_path, j.work_dir);
          setTranslation(tr);
          if (deliveryMode === "dub") {
            const d = await dubVideo(tr.translated_srt_path, j.work_dir, j.meta.source_url);
            setDub(d);
          }
        } else {
          const sc = await summarizeScript(t.srt_path, j.work_dir, j.meta.title, j.meta.chapters);
          setScript(sc);
          const au = await synthesizeScript(sc.script_json_path, j.work_dir);
          setAudio(au);
        }
        setProgress(null);
      } catch (e) {
        setError(String(e));
      } finally {
        setBusy(false);
        setProgress(null);
      }
    },
    [url, translationMode, deliveryMode, resetPipeline],
  );

  const runTranscribe = useCallback(async () => {
    if (!job?.artifacts.extracted_wav) return;
    setBusy(true);
    setError(null);
    setTranscript(null);
    setTranslation(null);
    setScript(null);
    setAudio(null);
    setDub(null);
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

  const runTranslate = useCallback(
    async (srtPath?: string) => {
      const srt = srtPath ?? transcript?.srt_path;
      if (!job || !srt) return;
      setBusy(true);
      setError(null);
      setTranslation(null);
      setDub(null);
      setProgress("和訳を開始しています…");
      try {
        setTranslation(await translateSrt(srt, job.work_dir));
      } catch (e) {
        setError(String(e));
      } finally {
        setBusy(false);
        setProgress(null);
      }
    },
    [job, transcript],
  );

  const runSummarize = useCallback(
    async (srtPath?: string) => {
      const srt = srtPath ?? transcript?.srt_path;
      if (!job || !srt) return;
      setBusy(true);
      setError(null);
      setScript(null);
      setAudio(null);
      setProgress("要約台本の生成を開始しています…");
      try {
        setScript(await summarizeScript(srt, job.work_dir, job.meta.title, job.meta.chapters));
      } catch (e) {
        setError(String(e));
      } finally {
        setBusy(false);
        setProgress(null);
      }
    },
    [job, transcript],
  );

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

  // Mirror the router's model pick so the chip shows what will actually run.
  const pickTranslationModel = (models: string[], preferred?: string): string | null => {
    if (models.length === 0) return null;
    if (preferred && models.includes(preferred)) return preferred;
    const tg = models.find((m) => m.toLowerCase().includes("translategemma"));
    if (tg) return tg;
    return models.find((m) => !m.toLowerCase().includes("embed")) ?? null;
  };

  const llmChip = (() => {
    const preferred = settings?.translation_model;
    if (backends?.ollama.available) {
      const model = pickTranslationModel(backends.ollama.models, preferred);
      return {
        on: true,
        label: `Ollama｜${model ?? "モデルなし"}`,
        title: `ローカルLLM（Ollama）に接続中。翻訳モデル: ${model ?? "なし"}\n保有モデル: ${backends.ollama.models.join(", ") || "なし"}`,
      };
    }
    if (backends?.lmstudio.available) {
      const model = pickTranslationModel(backends.lmstudio.models, preferred);
      return {
        on: true,
        label: `LM Studio｜${model ?? "モデルなし"}`,
        title: `Ollama 未起動のため LM Studio（ローカル）を使用します。翻訳モデル: ${model ?? "なし"}`,
      };
    }
    if (orKeySet && settings?.openrouter_model) {
      return {
        on: true,
        label: `OpenRouter｜${settings.openrouter_model}`,
        title: "ローカルLLMが見つからないため、クラウド（OpenRouter）を使用します",
      };
    }
    return {
      on: false,
      label: "LLM なし",
      title:
        "翻訳・要約に使えるLLMがありません。Ollama / LM Studio を起動するか、設定で OpenRouter を登録してください",
    };
  })();

  return (
    <main className="container">
      <header className="app-header">
        <h1>linguacast</h1>
        <span className="tagline">外国語の一次情報を、日本語の音声で。</span>
        <div className="header-right">
          <span
            className={`engine-chip ${llmChip.on ? "engine-on" : "engine-off"}`}
            title={llmChip.title}
          >
            ● {llmChip.label}
          </span>
          {tts?.voicevox_available ? (
            <span
              className="engine-chip engine-on"
              title={`VOICEVOX 稼働中（v${tts.voicevox_version}）`}
            >
              ● VOICEVOX
            </span>
          ) : tts?.edge_available ? (
            <span
              className="engine-chip engine-on"
              title="VOICEVOX 未起動のため、無料の Edge TTS（Microsoft音声）で読み上げます"
            >
              ● Edge TTS
            </span>
          ) : (
            <span
              className="engine-chip engine-off"
              title="音声合成が利用できません（VOICEVOX 未起動・Edge TTS 不可）"
            >
              ● TTS
            </span>
          )}
          <button
            className="gear-btn"
            onClick={() => setShowSettings((v) => !v)}
            aria-expanded={showSettings}
          >
            ⚙ 設定
          </button>
        </div>
      </header>

      {showSettings && settings && (
        <section className="media-card settings-panel">
          <div className="section-label">設定</div>

          <div className="settings-grid">
            <label className="settings-label">翻訳モデル</label>
            <select
              className="model-select"
              value={settings.translation_model}
              onChange={(e) => changeSetting({ translation_model: e.target.value })}
            >
              {modelChoices.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>

            <label className="settings-label">原語（翻訳元）</label>
            <select
              className="model-select"
              value={settings.source_lang}
              onChange={(e) => changeSetting({ source_lang: e.target.value })}
            >
              {["en", "es", "fr", "de", "zh", "ko", "pt", "it", "ru"].map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </select>

            <label className="settings-label">VOICEVOX: ナレーター / ホスト音声</label>
            <select
              className="model-select"
              value={settings.narrator_voice}
              onChange={(e) => changeSetting({ narrator_voice: Number(e.target.value) })}
              disabled={voiceChoices.length === 0}
            >
              {voiceChoices.length === 0 && (
                <option value={settings.narrator_voice}>（VOICEVOX 未接続）</option>
              )}
              {voiceChoices.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.label}
                </option>
              ))}
            </select>

            <label className="settings-label">VOICEVOX: ゲスト音声</label>
            <div>
              <select
                className="model-select"
                value={settings.guest_voice}
                onChange={(e) => changeSetting({ guest_voice: Number(e.target.value) })}
                disabled={voiceChoices.length === 0}
              >
                {voiceChoices.length === 0 && (
                  <option value={settings.guest_voice}>（VOICEVOX 未接続）</option>
                )}
                {voiceChoices.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label}
                  </option>
                ))}
              </select>
              <div className="mode-note">
                ※
                ゲスト音声は「要約」の対話台本で使われます。吹き替えは現在ナレーター音声のみ（話者の自動判別は将来対応予定）
              </div>
            </div>

            <label className="settings-label">Edge TTS: ナレーター / ホスト音声</label>
            <select
              className="model-select"
              value={settings.edge_narrator_voice}
              onChange={(e) => changeSetting({ edge_narrator_voice: e.target.value })}
            >
              {edgeVoiceList.length === 0 && (
                <option value={settings.edge_narrator_voice}>{settings.edge_narrator_voice}</option>
              )}
              {edgeVoiceList.map((v) => (
                <option key={v.short_name} value={v.short_name}>
                  {v.short_name}（{v.gender === "Female" ? "女性" : "男性"}）
                </option>
              ))}
            </select>

            <label className="settings-label">Edge TTS: ゲスト音声</label>
            <select
              className="model-select"
              value={settings.edge_guest_voice}
              onChange={(e) => changeSetting({ edge_guest_voice: e.target.value })}
            >
              {edgeVoiceList.length === 0 && (
                <option value={settings.edge_guest_voice}>{settings.edge_guest_voice}</option>
              )}
              {edgeVoiceList.map((v) => (
                <option key={v.short_name} value={v.short_name}>
                  {v.short_name}（{v.gender === "Female" ? "女性" : "男性"}）
                </option>
              ))}
            </select>

            <label className="settings-label">
              OpenRouter APIキー
              <span className={orKeySet ? "key-state key-ok" : "key-state"}>
                {orKeySet ? "保存済み" : "未設定"}
              </span>
            </label>
            <div className="key-row">
              <input
                className="url-input key-input"
                type="password"
                placeholder="sk-or-...（空で保存するとクリア）"
                value={orKeyInput}
                onChange={(e) => setOrKeyInput(e.target.value)}
              />
              <button className="start-btn" onClick={() => void saveOrKey()}>
                保存
              </button>
            </div>

            <label className="settings-label">OpenRouter モデル</label>
            <div>
              <input
                className="url-input key-input"
                type="text"
                list="openrouter-model-list"
                placeholder={
                  orModels.length > 0
                    ? "クリックして選択（入力で絞り込み）"
                    : "例: anthropic/claude-sonnet-5"
                }
                value={settings.openrouter_model ?? ""}
                onChange={(e) => changeSetting({ openrouter_model: e.target.value || null })}
              />
              <datalist id="openrouter-model-list">
                {orModels.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </datalist>
              {orModels.length > 0 && (
                <div className="mode-note">{orModels.length} モデルから選択できます</div>
              )}
            </div>

            <label className="settings-label">
              Google Cloud TTS APIキー
              <span className={googleKeySet ? "key-state key-ok" : "key-state"}>
                {googleKeySet ? "保存済み" : "未設定"}
              </span>
            </label>
            <div className="key-row">
              <input
                className="url-input key-input"
                type="password"
                placeholder="AIza...（空で保存するとクリア）"
                value={googleKeyInput}
                onChange={(e) => setGoogleKeyInput(e.target.value)}
              />
              <button className="start-btn" onClick={() => void saveGoogleKey()}>
                保存
              </button>
            </div>
          </div>

          <div className="section-label settings-section">プリセットチャンネルの編集</div>
          {presets.map((cat, ci) => (
            <div className="preset-category" key={cat.category}>
              <div className="category-heading">{cat.category}</div>
              {cat.channels.map((ch, xi) => (
                <div className="preset-edit-row" key={ch.url}>
                  <span className="upload-title">{ch.label}</span>
                  <span className="preset-edit-actions">
                    <button className="mini-btn" onClick={() => movePreset(ci, xi, -1)}>
                      ↑
                    </button>
                    <button className="mini-btn" onClick={() => movePreset(ci, xi, 1)}>
                      ↓
                    </button>
                    <button className="mini-btn mini-danger" onClick={() => removePreset(ci, xi)}>
                      削除
                    </button>
                  </span>
                </div>
              ))}
            </div>
          ))}
          <div className="preset-add-row">
            <input
              className="url-input key-input"
              placeholder="カテゴリ（例: AI）"
              value={newPreset.category}
              onChange={(e) => setNewPreset({ ...newPreset, category: e.target.value })}
            />
            <input
              className="url-input key-input"
              placeholder="表示名"
              value={newPreset.label}
              onChange={(e) => setNewPreset({ ...newPreset, label: e.target.value })}
            />
            <input
              className="url-input key-input"
              placeholder="チャンネルURL"
              value={newPreset.url}
              onChange={(e) => setNewPreset({ ...newPreset, url: e.target.value })}
            />
            <button className="start-btn" onClick={addPreset}>
              追加
            </button>
          </div>

          <div className="legal-note">
            ⚠️ ご利用にあたって: linguacast
            は個人の学習利用を前提としています。他者の著作物（YouTube
            動画など）から生成した翻訳・音声・動画を公開・再配布すると、著作権や各サービスの利用規約に抵触するおそれがあります。生成物の取り扱いは利用者ご自身の責任でお願いします。
          </div>
        </section>
      )}

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

      {tts && !tts.voicevox_available && (
        <section className="banner banner-warn" role="alert">
          <strong>VOICEVOX が起動していません</strong>
          <div className="banner-detail">{tts.warning}</div>
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
            if (e.key === "Enter" && canStart) void runPipeline();
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
              disabled={busy || translationMode === "summary"}
            >
              字幕のみ
            </button>
            <button
              className={deliveryMode === "dub" ? "seg active" : "seg"}
              onClick={() => setDeliveryMode("dub")}
              disabled={busy || translationMode === "summary"}
            >
              吹き替え
            </button>
          </div>

          {translationMode === "summary" && (
            <span className="mode-note">
              要約モードでは日本語ポッドキャスト音声（wav）を生成します（吹き替え動画は「全訳」モードで）
            </span>
          )}

          <button
            className="start-btn"
            onClick={() => void runPipeline()}
            disabled={!canStart}
            title="選択した出力モードに従って最後まで自動実行します"
          >
            ▶ 一括実行
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
          <button
            className="link-btn"
            onClick={() => void runPrepare()}
            disabled={!canStart}
            title="音声の取得・抽出だけ行い、以降は各ステップのボタンで手動実行します"
          >
            取得のみ（手動ステップ）
          </button>
        </div>

        <div
          className={`drop-zone${dragActive ? " drop-active" : ""}${busy ? " drop-disabled" : ""}`}
          role="button"
          tabIndex={0}
          onClick={() => {
            if (!busy) void runOpenLocal();
          }}
          onKeyDown={(e) => {
            if ((e.key === "Enter" || e.key === " ") && !busy) void runOpenLocal();
          }}
          title="ダウンロード済みの音声・動画ファイルから開始します"
        >
          📂 ここに音声・動画ファイルをドロップ
          <span className="drop-sub">（クリックでファイル選択）</span>
        </div>
      </section>

      {busy && progress && (
        <section className="banner banner-info">
          <div className="progress-line">
            <span className="spinner" aria-hidden /> {progress}
          </div>
          {progressPercent != null && (
            <div className="progress-track" aria-hidden>
              <div className="progress-fill" style={{ width: `${progressPercent}%` }} />
            </div>
          )}
        </section>
      )}

      {error && (
        <section className="banner banner-error" role="alert">
          {error}
        </section>
      )}

      {preview && !job && <MediaCard meta={preview} title="メタ情報" />}

      {resume && job && (
        <section className="artifact-card">
          <div className="section-label">再開ポイント（保存済みの中間成果物）</div>
          {resume.artifacts.source_srt && (
            <div className="artifact-row">
              <span className="artifact-label">原語 SRT</span>
              <button
                className="start-btn"
                onClick={() =>
                  resume.artifacts.source_srt && void runTranslate(resume.artifacts.source_srt)
                }
                disabled={busy}
              >
                和訳 (SRT)
              </button>
              <button
                className="start-btn"
                onClick={() =>
                  resume.artifacts.source_srt && void runSummarize(resume.artifacts.source_srt)
                }
                disabled={busy}
              >
                要約台本を生成
              </button>
            </div>
          )}
          {resume.artifacts.translated_srt && (
            <div className="artifact-row">
              <span className="artifact-label">和訳 SRT</span>
              <button
                className="start-btn"
                onClick={() =>
                  resume.artifacts.translated_srt && void runDub(resume.artifacts.translated_srt)
                }
                disabled={busy}
              >
                吹き替え動画を生成
              </button>
            </div>
          )}
          {resume.artifacts.script_json && (
            <div className="artifact-row">
              <span className="artifact-label">台本 (JSON)</span>
              <button
                className="start-btn"
                onClick={() =>
                  resume.artifacts.script_json && void runSynthesize(resume.artifacts.script_json)
                }
                disabled={busy}
              >
                音声を生成
              </button>
            </div>
          )}
          {resume.artifacts.audio_wav && (
            <div className="artifact-row">
              <span className="artifact-label">ポッドキャスト音声</span>
              <button
                className="start-btn"
                onClick={() =>
                  resume.artifacts.audio_wav && void runShare(resume.artifacts.audio_wav)
                }
                disabled={busy}
              >
                📱 QRで送る
              </button>
            </div>
          )}
          {resume.artifacts.dubbed_video && (
            <div className="artifact-row">
              <span className="artifact-label">吹き替え動画</span>
              <button
                className="start-btn"
                onClick={() =>
                  resume.artifacts.dubbed_video && void runShare(resume.artifacts.dubbed_video)
                }
                disabled={busy}
              >
                📱 QRで送る
              </button>
            </div>
          )}
        </section>
      )}

      {job && (
        <>
          <MediaCard meta={job.meta} title={resume ? "ジョブを再開" : "音声準備 完了"} />
          <section className="artifact-card">
            <div className="artifact-row">
              <span className="artifact-label">ジョブ ID</span>
              <code>{job.id}</code>
            </div>
            <div className="artifact-row">
              <span className="artifact-label">作業フォルダ</span>
              <code className="path">{job.work_dir}</code>
              <button
                className="mini-btn"
                onClick={() => void openWorkDir(job.work_dir).catch((e) => setError(String(e)))}
                title="エクスプローラーで開く"
              >
                📁 開く
              </button>
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
                onClick={() => void runPipeline(job)}
                disabled={busy || !job.artifacts.extracted_wav}
                title="選択した出力モードに従って最後まで自動実行します"
              >
                ⚡ ここから一括実行
              </button>
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
            <button
              className="start-btn"
              onClick={() => void runSummarize()}
              disabled={busy || !transcript.srt_path}
            >
              要約台本を生成
            </button>
          </div>
        </section>
      )}

      {script && (
        <section className="media-card">
          <div className="media-card-head">
            <span className="section-label">ポッドキャスト台本 完了</span>
            <span className="routing-badge routing-short">
              {script.format === "dialogue" ? "対話形式" : "ナレーション"} /{" "}
              {script.strategy === "hierarchical" ? "階層要約" : "1パス要約"}
            </span>
          </div>
          <div className="media-title">{script.title}</div>
          <div className="media-meta">
            <span>{tierLabel(script.tier)}</span>
            <span>モデル: {script.model}</span>
            <span>
              {script.line_count} 行 / {script.section_count} セクション
            </span>
          </div>
          <div className="artifact-row">
            <span className="artifact-label">台本</span>
            <code className="path">{script.script_txt_path}</code>
            {job && (
              <button
                className="mini-btn"
                onClick={() => void openWorkDir(job.work_dir).catch((e) => setError(String(e)))}
                title="エクスプローラーで開く"
              >
                📁 開く
              </button>
            )}
          </div>
          <div className="transcript-preview">
            {script.lines.slice(0, 8).map((l, i) => (
              <div className="transcript-line" key={i}>
                <span className="transcript-time">{l.speaker}</span>
                <span>{l.text}</span>
              </div>
            ))}
            {script.lines.length > 8 && (
              <div className="transcript-more">… 他 {script.lines.length - 8} 行</div>
            )}
          </div>
          <div className="artifact-row">
            <span className="artifact-label">
              {script.format === "dialogue" ? "ホスト音声" : "ナレーター音声"}
            </span>
            <select
              className="model-select"
              value={settings?.narrator_voice ?? 3}
              onChange={(e) => changeVoice("narrator_voice", Number(e.target.value))}
              disabled={busy || voiceChoices.length === 0}
            >
              {voiceChoices.length === 0 && <option value={3}>（VOICEVOX 未接続）</option>}
              {voiceChoices.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.label}
                </option>
              ))}
            </select>
            {script.format === "dialogue" && (
              <select
                className="model-select"
                value={settings?.guest_voice ?? 2}
                onChange={(e) => changeVoice("guest_voice", Number(e.target.value))}
                disabled={busy || voiceChoices.length === 0}
                aria-label="ゲスト音声"
              >
                {voiceChoices.length === 0 && <option value={2}>（VOICEVOX 未接続）</option>}
                {voiceChoices.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label}
                  </option>
                ))}
              </select>
            )}
            <button className="start-btn" onClick={() => void runSynthesize()} disabled={busy}>
              音声を生成
            </button>
          </div>
        </section>
      )}

      {audio && (
        <section className="media-card">
          <div className="media-card-head">
            <span className="section-label">音声合成 完了</span>
            <span className="routing-badge routing-short">
              {TTS_ENGINE_LABELS[audio.engine] ?? audio.engine}
            </span>
          </div>
          <div className="media-meta">
            <span>{audio.line_count} 行を合成</span>
          </div>
          <div className="artifact-row">
            <span className="artifact-label">音声ファイル</span>
            <code className="path">{audio.audio_path}</code>
            <button
              className="start-btn"
              onClick={() => void runShare(audio.audio_path)}
              disabled={busy}
            >
              📱 QRで送る
            </button>
            {job && (
              <button
                className="mini-btn"
                onClick={() => void openWorkDir(job.work_dir).catch((e) => setError(String(e)))}
                title="エクスプローラーで開く"
              >
                📁 開く
              </button>
            )}
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
            {job && (
              <button
                className="mini-btn"
                onClick={() => void openWorkDir(job.work_dir).catch((e) => setError(String(e)))}
                title="エクスプローラーで開く"
              >
                📁 開く
              </button>
            )}
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
          <div className="artifact-row">
            <span className="artifact-label">吹き替えモード</span>
            <button className="start-btn" onClick={() => void runDub()} disabled={busy}>
              吹き替え動画を生成
            </button>
            <span className="mode-note">元動画に日本語トラックを同期・多重化します</span>
          </div>
        </section>
      )}

      {dub && (
        <section className="media-card">
          <div className="media-card-head">
            <span className="section-label">吹き替え 完了</span>
            <span className="routing-badge routing-short">
              {TTS_ENGINE_LABELS[dub.engine] ?? dub.engine} / {dub.segment_count} セグメント同期
            </span>
          </div>
          <div className="media-meta">
            {Object.entries(dub.fit_summary).map(([method, count]) => (
              <span key={method}>
                {FIT_METHOD_LABELS[method] ?? method}: {count}
              </span>
            ))}
          </div>
          {dub.dubbed_video_path && (
            <div className="artifact-row">
              <span className="artifact-label">吹き替え動画</span>
              <code className="path">{dub.dubbed_video_path}</code>
              <button
                className="start-btn"
                onClick={() => dub.dubbed_video_path && void runShare(dub.dubbed_video_path)}
                disabled={busy}
              >
                📱 QRで送る
              </button>
              {job && (
                <button
                  className="mini-btn"
                  onClick={() => void openWorkDir(job.work_dir).catch((e) => setError(String(e)))}
                  title="エクスプローラーで開く"
                >
                  📁 開く
                </button>
              )}
            </div>
          )}
          <div className="artifact-row">
            <span className="artifact-label">日本語トラック</span>
            <code className="path">{dub.dubbed_audio_path}</code>
            <button
              className="start-btn"
              onClick={() => void runShare(dub.dubbed_audio_path)}
              disabled={busy}
            >
              📱 QRで送る
            </button>
            {job && !dub.dubbed_video_path && (
              <button
                className="mini-btn"
                onClick={() => void openWorkDir(job.work_dir).catch((e) => setError(String(e)))}
                title="エクスプローラーで開く"
              >
                📁 開く
              </button>
            )}
          </div>
        </section>
      )}

      {share && (
        <section className="media-card">
          <div className="media-card-head">
            <span className="section-label">QRダウンロード</span>
            <span className="routing-badge routing-short">有効期限 {share.expires_min} 分</span>
          </div>
          <div className="qr-row">
            <div className="qr-box">
              <QRCodeSVG value={share.url} size={180} marginSize={2} />
            </div>
            <div className="qr-info">
              <div className="media-title">{share.filename}</div>
              <div className="qr-url">{share.url}</div>
              <p className="mode-note">
                同一 Wi-Fi / LAN 上のスマホでこの QR
                を読み取ると、ブラウザで再生・ダウンロードできます（シーク再生対応）。
              </p>
              <p className="mode-note">
                ※ 初回は Windows
                ファイアウォールの確認が表示される場合があります。「プライベートネットワーク」で許可してください。
              </p>
            </div>
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

      {jobs.length > 0 && (
        <section className="presets">
          <div className="section-label">最近のジョブ（クリックで再開）</div>
          {jobs.map((j) => (
            <button className="upload-item" key={j.id} onClick={() => resumeJob(j)} disabled={busy}>
              <span className="upload-title">{j.meta.title}</span>
              <span className="upload-dur">
                {[
                  j.artifacts.source_srt && "SRT",
                  j.artifacts.translated_srt && "和訳",
                  j.artifacts.script_json && "台本",
                  j.artifacts.audio_wav && "音声",
                  j.artifacts.dubbed_video && "吹替",
                ]
                  .filter(Boolean)
                  .join("・") || "音声準備"}
                {" / "}
                {formatDuration(j.meta.duration_sec)}
              </span>
            </button>
          ))}
        </section>
      )}

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
