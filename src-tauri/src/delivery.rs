//! LAN delivery server for QR downloads (architecture.md §7, gotcha #7).
//!
//! Binds `0.0.0.0` lazily on first share (so the Windows Firewall prompt only
//! appears when the feature is actually used) and serves files with HTTP range
//! support (mobile seek/stream) behind unguessable, expiring tokens.

use std::collections::HashMap;
use std::net::IpAddr;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use axum::body::Body;
use axum::extract::{Path as UrlPath, Request, State};
use axum::http::{header, HeaderValue, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use axum::Router;
use serde::Serialize;
use tower::ServiceExt;
use tower_http::services::ServeFile;
use uuid::Uuid;

/// Download links expire after this long.
pub const TOKEN_TTL: Duration = Duration::from_secs(60 * 60);

struct TokenEntry {
    path: PathBuf,
    filename: String,
    expires_at: Instant,
}

#[derive(Default)]
pub struct DeliveryState {
    tokens: Mutex<HashMap<String, TokenEntry>>,
    // tokio Mutex so ensure_server can hold it across the bind await.
    port: tokio::sync::Mutex<Option<u16>>,
}

#[derive(Serialize)]
pub struct ShareInfo {
    pub url: String,
    pub filename: String,
    pub lan_ip: String,
    pub port: u16,
    pub expires_min: u64,
}

/// Start the delivery server once and return its port.
pub async fn ensure_server(state: Arc<DeliveryState>) -> Result<u16, String> {
    let mut guard = state.port.lock().await;
    if let Some(port) = *guard {
        return Ok(port);
    }

    let app = Router::new()
        .route("/download/{token}", get(download))
        .with_state(state.clone());

    let listener = tokio::net::TcpListener::bind(("0.0.0.0", 0))
        .await
        .map_err(|e| format!("cannot bind delivery server: {e}"))?;
    let port = listener
        .local_addr()
        .map_err(|e| format!("cannot read local addr: {e}"))?
        .port();

    tokio::spawn(async move {
        if let Err(e) = axum::serve(listener, app).await {
            eprintln!("[delivery] server stopped: {e}");
        }
    });

    *guard = Some(port);
    Ok(port)
}

/// Register a file and return a share descriptor with a tokenized URL.
pub async fn share_file(state: Arc<DeliveryState>, path: String) -> Result<ShareInfo, String> {
    let pb = PathBuf::from(&path);
    if !pb.is_file() {
        return Err(format!("ファイルが見つかりません: {path}"));
    }
    let filename = pb
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_else(|| "download".to_string());

    let port = ensure_server(state.clone()).await?;
    let lan_ip = lan_ip().ok_or_else(|| {
        "LAN の IP アドレスを特定できません。Wi-Fi / LAN に接続しているか確認してください。"
            .to_string()
    })?;

    let token = Uuid::new_v4().to_string();
    state.tokens.lock().unwrap().insert(
        token.clone(),
        TokenEntry {
            path: pb,
            filename: filename.clone(),
            expires_at: Instant::now() + TOKEN_TTL,
        },
    );

    Ok(ShareInfo {
        url: format!("http://{lan_ip}:{port}/download/{token}"),
        filename,
        lan_ip,
        port,
        expires_min: TOKEN_TTL.as_secs() / 60,
    })
}

async fn download(
    State(state): State<Arc<DeliveryState>>,
    UrlPath(token): UrlPath<String>,
    req: Request,
) -> Response {
    let entry = {
        let mut tokens = state.tokens.lock().unwrap();
        match tokens.get(&token) {
            Some(e) if e.expires_at > Instant::now() => Some((e.path.clone(), e.filename.clone())),
            Some(_) => {
                tokens.remove(&token);
                None
            }
            None => None,
        }
    };

    let Some((path, filename)) = entry else {
        return (StatusCode::NOT_FOUND, "リンクが無効か、期限切れです。").into_response();
    };

    // ServeFile implements range requests (206/Content-Range) for us.
    match ServeFile::new(&path).oneshot(req).await {
        Ok(mut res) => {
            let cd = format!("inline; filename*=UTF-8''{}", percent_encode(&filename));
            if let Ok(v) = HeaderValue::from_str(&cd) {
                res.headers_mut().insert(header::CONTENT_DISPOSITION, v);
            }
            res.map(Body::new).into_response()
        }
        Err(e) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            format!("file error: {e}"),
        )
            .into_response(),
    }
}

/// Best LAN IPv4: prefer 192.168/10.x private ranges and skip virtual adapters
/// (WSL / Hyper-V vEthernet / Docker) that phones cannot reach.
pub fn lan_ip() -> Option<String> {
    let ifas = local_ip_address::list_afinet_netifas().ok()?;
    let mut best: Option<(u8, String)> = None;
    for (name, ip) in ifas {
        let IpAddr::V4(v4) = ip else { continue };
        if v4.is_loopback() || v4.is_link_local() {
            continue;
        }
        let lname = name.to_lowercase();
        if ["wsl", "vethernet", "docker", "virtual", "loopback"]
            .iter()
            .any(|k| lname.contains(k))
        {
            continue;
        }
        let o = v4.octets();
        let score = if o[0] == 192 && o[1] == 168 {
            3
        } else if o[0] == 10 {
            2
        } else if o[0] == 172 && (16..=31).contains(&o[1]) {
            1
        } else {
            0
        };
        if score > 0 && best.as_ref().is_none_or(|(s, _)| score > *s) {
            best = Some((score, v4.to_string()));
        }
    }
    best.map(|(_, ip)| ip)
}

fn percent_encode(s: &str) -> String {
    let mut out = String::new();
    for b in s.as_bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'.' | b'-' | b'_' => out.push(*b as char),
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    async fn setup(bytes: &[u8]) -> (Arc<DeliveryState>, u16, String) {
        let state = Arc::new(DeliveryState::default());
        let port = ensure_server(state.clone()).await.unwrap();

        let mut f = tempfile_path();
        f.1.write_all(bytes).unwrap();
        f.1.flush().unwrap();

        let token = Uuid::new_v4().to_string();
        state.tokens.lock().unwrap().insert(
            token.clone(),
            TokenEntry {
                path: f.0.clone(),
                filename: "テスト音声.wav".to_string(),
                expires_at: Instant::now() + Duration::from_secs(60),
            },
        );
        // Leak the file handle so Windows keeps the file readable for the test.
        std::mem::forget(f.1);
        (state, port, token)
    }

    fn tempfile_path() -> (PathBuf, std::fs::File) {
        let dir = std::env::temp_dir();
        let path = dir.join(format!("linguacast-test-{}.bin", Uuid::new_v4()));
        let file = std::fs::File::create(&path).unwrap();
        (path, file)
    }

    #[tokio::test]
    async fn serves_full_file_with_range_support_advertised() {
        let data: Vec<u8> = (0..=255u8).cycle().take(1000).collect();
        let (_state, port, token) = setup(&data).await;

        let res = reqwest::get(format!("http://127.0.0.1:{port}/download/{token}"))
            .await
            .unwrap();
        assert_eq!(res.status(), 200);
        assert_eq!(
            res.headers()
                .get("accept-ranges")
                .unwrap()
                .to_str()
                .unwrap(),
            "bytes"
        );
        assert!(res
            .headers()
            .get("content-disposition")
            .unwrap()
            .to_str()
            .unwrap()
            .starts_with("inline; filename*=UTF-8''"));
        let body = res.bytes().await.unwrap();
        assert_eq!(body.as_ref(), data.as_slice());
    }

    #[tokio::test]
    async fn serves_partial_content_for_range_requests() {
        let data: Vec<u8> = (0..=255u8).cycle().take(1000).collect();
        let (_state, port, token) = setup(&data).await;

        let client = reqwest::Client::new();
        let res = client
            .get(format!("http://127.0.0.1:{port}/download/{token}"))
            .header("Range", "bytes=100-199")
            .send()
            .await
            .unwrap();
        assert_eq!(res.status(), 206);
        let content_range = res
            .headers()
            .get("content-range")
            .unwrap()
            .to_str()
            .unwrap()
            .to_string();
        assert_eq!(content_range, "bytes 100-199/1000");
        let body = res.bytes().await.unwrap();
        assert_eq!(body.as_ref(), &data[100..200]);
    }

    #[tokio::test]
    async fn rejects_unknown_and_expired_tokens() {
        let (state, port, token) = setup(b"hello").await;

        // Unknown token.
        let res = reqwest::get(format!("http://127.0.0.1:{port}/download/nope"))
            .await
            .unwrap();
        assert_eq!(res.status(), 404);

        // Expire the real token, then it must be rejected too.
        state
            .tokens
            .lock()
            .unwrap()
            .get_mut(&token)
            .unwrap()
            .expires_at = Instant::now() - Duration::from_secs(1);
        let res = reqwest::get(format!("http://127.0.0.1:{port}/download/{token}"))
            .await
            .unwrap();
        assert_eq!(res.status(), 404);
    }
}
