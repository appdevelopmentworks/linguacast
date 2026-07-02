mod commands;
mod config;
mod delivery;
mod deps;
mod external;
mod media;
mod secrets;
mod sidecar;

use std::sync::Arc;

use sidecar::SidecarManager;
use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            // The sidecar manager owns the child process lifecycle and resolved port.
            let manager = Arc::new(SidecarManager::new());
            app.manage(manager.clone());
            // Delivery server state (bound lazily on first QR share).
            app.manage(Arc::new(delivery::DeliveryState::default()));

            // Spawn the FastAPI sidecar and health-check it in the background so the
            // window opens immediately. Per the fallback contract, a failed start is
            // a warning (logged + surfaced via ping_sidecar), never a crash.
            tauri::async_runtime::spawn(async move {
                if let Err(err) = manager.start().await {
                    eprintln!("[sidecar] failed to start: {err}");
                }
            });

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::ping_sidecar,
            commands::sidecar_status,
            commands::check_dependencies,
            commands::fetch_metadata,
            commands::prepare_media,
            commands::list_channel_uploads,
            commands::get_presets,
            commands::save_presets,
            commands::transcribe,
            commands::get_settings,
            commands::save_settings,
            commands::set_openrouter_key,
            commands::has_openrouter_key,
            commands::translate_backends,
            commands::translate_srt,
            commands::summarize_script,
            commands::tts_status,
            commands::synthesize_script,
            commands::set_google_tts_key,
            commands::has_google_tts_key,
            commands::dub_video,
            commands::share_file,
            commands::prepare_local_media,
            commands::list_jobs,
            commands::open_work_dir,
            commands::openrouter_models,
            commands::edge_voices
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            // Make sure we don't leave an orphaned uvicorn process behind.
            if let tauri::RunEvent::ExitRequested { .. } = event {
                if let Some(manager) = app_handle.try_state::<Arc<SidecarManager>>() {
                    manager.shutdown();
                }
            }
        });
}
