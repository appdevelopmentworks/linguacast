//! Lifecycle management for the Python FastAPI sidecar.
//!
//! In development the sidecar lives next to `src-tauri` in the repo and is run
//! via `uv run`. Production packaging (PyInstaller -> Tauri externalBin) is a
//! later-session concern; only the dev path is wired here.

use std::path::PathBuf;
use std::process::Stdio;
use std::sync::atomic::{AtomicU16, Ordering};
use std::sync::Mutex;
use std::time::Duration;

use tokio::process::{Child, Command};
use tokio::time::{sleep, Instant};

/// How long to wait for the sidecar to answer /health before giving up.
const HEALTH_TIMEOUT: Duration = Duration::from_secs(90);
const POLL_INTERVAL: Duration = Duration::from_millis(500);

pub struct SidecarManager {
    child: Mutex<Option<Child>>,
    port: AtomicU16,
}

impl SidecarManager {
    pub fn new() -> Self {
        Self {
            child: Mutex::new(None),
            port: AtomicU16::new(0),
        }
    }

    /// Resolved sidecar port, or 0 if it has not been spawned yet.
    pub fn port(&self) -> u16 {
        self.port.load(Ordering::SeqCst)
    }

    pub fn base_url(&self) -> String {
        format!("http://127.0.0.1:{}", self.port())
    }

    /// Spawn the sidecar on a free loopback port and wait until it is healthy.
    pub async fn start(&self) -> Result<(), String> {
        let port = pick_free_port().map_err(|e| format!("could not find a free port: {e}"))?;
        let dir = sidecar_dir()?;

        let mut cmd = Command::new("uv");
        cmd.arg("run")
            .arg("uvicorn")
            .arg("app.main:app")
            .arg("--host")
            .arg("127.0.0.1")
            .arg("--port")
            .arg(port.to_string())
            .current_dir(&dir)
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            // Backstop against orphaned processes if shutdown() is missed.
            .kill_on_drop(true);

        let child = cmd
            .spawn()
            .map_err(|e| format!("failed to spawn `uv run uvicorn` (is uv installed?): {e}"))?;

        self.port.store(port, Ordering::SeqCst);
        {
            let mut guard = self.child.lock().unwrap();
            *guard = Some(child);
        }

        wait_for_health(port).await
    }

    /// Terminate the sidecar child process, if any.
    pub fn shutdown(&self) {
        if let Ok(mut guard) = self.child.lock() {
            if let Some(mut child) = guard.take() {
                let _ = child.start_kill();
            }
        }
    }
}

fn pick_free_port() -> std::io::Result<u16> {
    // Binding to port 0 lets the OS hand us an unused port; we drop the listener
    // immediately and pass the port to uvicorn.
    let listener = std::net::TcpListener::bind("127.0.0.1:0")?;
    Ok(listener.local_addr()?.port())
}

fn sidecar_dir() -> Result<PathBuf, String> {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let dir = manifest_dir
        .parent()
        .ok_or_else(|| "cannot resolve repo root from CARGO_MANIFEST_DIR".to_string())?
        .join("sidecar");

    if dir.exists() {
        Ok(dir)
    } else {
        Err(format!("sidecar directory not found: {}", dir.display()))
    }
}

async fn wait_for_health(port: u16) -> Result<(), String> {
    let url = format!("http://127.0.0.1:{port}/health");
    let client = reqwest::Client::new();
    let deadline = Instant::now() + HEALTH_TIMEOUT;

    loop {
        if let Ok(resp) = client.get(&url).send().await {
            if resp.status().is_success() {
                return Ok(());
            }
        }
        if Instant::now() >= deadline {
            return Err("sidecar health check timed out".to_string());
        }
        sleep(POLL_INTERVAL).await;
    }
}
