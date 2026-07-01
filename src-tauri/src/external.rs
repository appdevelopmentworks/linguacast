//! Helpers for running external CLI tools (yt-dlp, ffmpeg, ffprobe).

use std::ffi::OsStr;
use std::process::Stdio;

use tokio::process::Command;

/// Run a command to completion and return its stdout on success. stderr is
/// folded into the error message so callers can surface a useful reason.
pub async fn run_capture<I, S>(program: &str, args: I) -> Result<String, String>
where
    I: IntoIterator<Item = S>,
    S: AsRef<OsStr>,
{
    let output = Command::new(program)
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output()
        .await
        .map_err(|e| format!("failed to run `{program}` (is it installed and on PATH?): {e}"))?;

    if output.status.success() {
        Ok(String::from_utf8_lossy(&output.stdout).into_owned())
    } else {
        let stderr = String::from_utf8_lossy(&output.stderr);
        Err(format!(
            "`{program}` exited with {}: {}",
            output.status,
            stderr.trim()
        ))
    }
}
