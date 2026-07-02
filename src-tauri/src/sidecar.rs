//! Lifecycle management for the Python FastAPI sidecar.
//!
//! Development runs it from the repo via `uv run`. Release runs the PyInstaller
//! single-file binary bundled as a Tauri resource (`binaries/`). Both spawn on
//! a free loopback port and are health-checked before use.

#[cfg(debug_assertions)]
use std::path::PathBuf;
use std::process::Stdio;
use std::sync::atomic::{AtomicU16, Ordering};
use std::sync::Mutex;
use std::time::Duration;

use tauri::AppHandle;
#[cfg(not(debug_assertions))]
use tauri::Manager;
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
    pub async fn start(&self, app: &AppHandle) -> Result<(), String> {
        let port = pick_free_port().map_err(|e| format!("could not find a free port: {e}"))?;

        let mut cmd = build_command(app, port)?;
        cmd.stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            // Backstop against orphaned processes if shutdown() is missed.
            .kill_on_drop(true);

        let child = cmd
            .spawn()
            .map_err(|e| format!("failed to spawn sidecar: {e}"))?;

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

/// Dev: `uv run uvicorn` from the repo sidecar dir. Release: the bundled
/// PyInstaller binary from the app's resource directory.
fn build_command(app: &AppHandle, port: u16) -> Result<Command, String> {
    #[cfg(debug_assertions)]
    {
        let _ = app;
        let dir = sidecar_dir()?;
        let mut cmd = Command::new("uv");
        cmd.arg("run")
            .arg("uvicorn")
            .arg("app.main:app")
            .arg("--host")
            .arg("127.0.0.1")
            .arg("--port")
            .arg(port.to_string())
            .current_dir(&dir);
        Ok(cmd)
    }

    #[cfg(not(debug_assertions))]
    {
        #[cfg(windows)]
        const BIN: &str = "linguacast-sidecar.exe";
        #[cfg(not(windows))]
        const BIN: &str = "linguacast-sidecar";

        let exe = app
            .path()
            .resource_dir()
            .map_err(|e| format!("cannot resolve resource dir: {e}"))?
            .join("binaries")
            .join(BIN);
        if !exe.exists() {
            return Err(format!("bundled sidecar not found: {}", exe.display()));
        }
        let mut cmd = Command::new(&exe);
        cmd.arg("--host")
            .arg("127.0.0.1")
            .arg("--port")
            .arg(port.to_string());
        Ok(cmd)
    }
}

#[cfg(debug_assertions)]
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
