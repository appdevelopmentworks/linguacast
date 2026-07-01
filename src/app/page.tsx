"use client";

import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

// Mirrors the SidecarHealth struct returned by the Rust `ping_sidecar` command.
type SidecarHealth = {
  reachable: boolean;
  status: string | null;
  service: string | null;
  version: string | null;
  detail: string | null;
};

export default function Home() {
  const [health, setHealth] = useState<SidecarHealth | null>(null);
  // We check on mount, so start in the "checking" state.
  const [checking, setChecking] = useState(true);

  // Only touches state after the awaited call, so it is safe to run from an
  // effect without tripping react-hooks/set-state-in-effect.
  const runCheck = useCallback(async () => {
    try {
      const result = await invoke<SidecarHealth>("ping_sidecar");
      setHealth(result);
    } catch (e) {
      // The command itself should not throw (fallback contract), but guard anyway.
      setHealth({
        reachable: false,
        status: null,
        service: null,
        version: null,
        detail: String(e),
      });
    } finally {
      setChecking(false);
    }
  }, []);

  // Manual re-check: setting state synchronously is fine in an event handler.
  const onRecheck = useCallback(() => {
    setChecking(true);
    void runCheck();
  }, [runCheck]);

  useEffect(() => {
    // Intentional one-shot fetch-on-mount: a valid external-system sync (the
    // sidecar's health). setState only runs after the awaited IPC resolves.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void runCheck();
  }, [runCheck]);

  const ok = health?.reachable ?? false;

  return (
    <main className="container">
      <h1>linguacast</h1>
      <p className="subtitle">外国語の一次情報を、日本語の音声で。</p>

      <section className="status-card">
        <div className={`status-dot ${ok ? "ok" : "ng"}`} aria-hidden />
        <div>
          <div className="status-title">
            {checking
              ? "サイドカーを確認しています…"
              : ok
                ? "サイドカー: 接続OK"
                : "サイドカー: 未接続"}
          </div>
          <div className="status-detail">
            {ok
              ? `${health?.service ?? "sidecar"} v${health?.version ?? "?"}`
              : (health?.detail ?? "FastAPI サイドカーに接続できません。")}
          </div>
        </div>
      </section>

      <button className="recheck" onClick={onRecheck} disabled={checking}>
        再チェック
      </button>
    </main>
  );
}
