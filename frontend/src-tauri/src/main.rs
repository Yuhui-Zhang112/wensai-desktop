#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

#[cfg(feature = "bundled-backend")]
mod backend {
    use std::sync::Mutex;
    use tauri::Manager;
    use tauri_plugin_shell::{process::CommandChild, ShellExt};

    pub struct Backend(pub Mutex<Option<CommandChild>>);

    pub fn start(app: &mut tauri::App) -> Result<(), Box<dyn std::error::Error>> {
        // The binary is supplied by A. No shell strings, user-provided executable or paths.
        let (mut events, child) = app.shell()
            .sidecar("review-api")?
            .args(["--host", "127.0.0.1", "--port", "8765"])
            .spawn()?;
        app.manage(Backend(Mutex::new(Some(child))));
        tauri::async_runtime::spawn(async move {
            // Drain output without recording user material, credentials or model prompts.
            while events.recv().await.is_some() {}
        });
        Ok(())
    }

    pub fn stop(app: &tauri::AppHandle) {
        if let Some(state) = app.try_state::<Backend>() {
            if let Ok(mut slot) = state.0.lock() {
                if let Some(child) = slot.take() {
                    // A must handle process termination and must not leave detached workers.
                    let _ = child.kill();
                }
            }
        }
    }
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            #[cfg(feature = "bundled-backend")]
            backend::start(app)?;
            #[cfg(not(feature = "bundled-backend"))]
            let _ = app;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Unable to start D review workspace");

    app.run(|app_handle, event| {
        #[cfg(feature = "bundled-backend")]
        if matches!(event, tauri::RunEvent::Exit) {
            backend::stop(app_handle);
        }
        #[cfg(not(feature = "bundled-backend"))]
        let _ = (app_handle, event);
    });
}
