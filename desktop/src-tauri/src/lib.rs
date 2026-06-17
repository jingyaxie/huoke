use std::io::{BufRead, BufReader, Read};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager, RunEvent, WindowEvent};

const DESKTOP_PORT: u16 = 18765;
const HEALTH_URL: &str = "http://127.0.0.1:18765/api/health";
const APP_HOME_URL: &str = "http://127.0.0.1:18765/cloud/dashboard";

struct ServiceState {
    backend: Mutex<Option<Child>>,
}

fn backend_script_name() -> &'static str {
    if cfg!(windows) {
        "desktop-run-backend.ps1"
    } else {
        "desktop-run-backend.sh"
    }
}

fn desktop_log_hint() -> &'static str {
    if cfg!(windows) {
        "%APPDATA%\\com.huoke.desktop\\logs\\desktop-backend.log"
    } else if cfg!(target_os = "macos") {
        "~/Library/Application Support/com.huoke.desktop/logs/desktop-backend.log"
    } else {
        "~/.local/share/huoke/logs/desktop-backend.log"
    }
}

fn find_launch_root(base: &Path) -> Option<PathBuf> {
    let backend_script = PathBuf::from("scripts").join(backend_script_name());
    let mut queue = vec![base.to_path_buf()];

    while let Some(current) = queue.pop() {
        if current.join(&backend_script).is_file() {
            return Some(current);
        }
        if let Ok(entries) = std::fs::read_dir(&current) {
            for entry in entries.filter_map(Result::ok) {
                let path = entry.path();
                if path.is_dir() {
                    queue.push(path);
                }
            }
        }
    }
    None
}

fn repo_root(app: &AppHandle) -> Result<PathBuf, String> {
    if let Ok(root) = std::env::var("HUOKE_ROOT") {
        let path = PathBuf::from(root);
        if let Some(found) = find_launch_root(&path) {
            return Ok(found);
        }
    }

    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|err| err.to_string())?;
    if let Some(found) = find_launch_root(&resource_dir) {
        return Ok(found);
    }

    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let dev_root = manifest_dir
        .parent()
        .and_then(|p| p.parent())
        .ok_or_else(|| "无法定位 Huoke 工程根目录".to_string())?;
    if let Some(found) = find_launch_root(dev_root) {
        return Ok(found);
    }

    Err("无法定位 Huoke 工程根目录，请重新安装应用".into())
}

fn spawn_log_reader<R>(stream: Option<R>, prefix: &'static str)
where
    R: Read + Send + 'static,
{
    if let Some(stream) = stream {
        thread::spawn(move || {
            let reader = BufReader::new(stream);
            for line in reader.lines().map_while(Result::ok) {
                log::info!("[{prefix}] {line}");
            }
        });
    }
}

fn resolve_bundle_dir(root: &Path) -> PathBuf {
    let candidates = [
        root.join("desktop/bundle"),
        root.join("bundle"),
    ];
    for dir in candidates {
        if dir.is_dir() {
            return dir;
        }
    }
    root.join("desktop/bundle")
}

fn start_backend(root: &PathBuf) -> Result<Child, String> {
    let script = root.join("scripts").join(backend_script_name());
    if !script.is_file() {
        return Err(format!("缺少脚本: {}", script.display()));
    }

    let bundle_dir = resolve_bundle_dir(root);

    let mut command = if cfg!(windows) {
        let mut cmd = Command::new("powershell");
        cmd.args([
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
        ]);
        cmd.arg(&script);
        cmd
    } else {
        let mut cmd = Command::new("/bin/bash");
        cmd.arg(&script);
        cmd
    };

    let mut child = command
        .current_dir(root)
        .env("HUOKE_ROOT", root)
        .env("HUOKE_BUNDLE_DIR", &bundle_dir)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|err| format!("启动后端失败: {err}"))?;

    if !cfg!(windows) {
        // macOS / Linux: ensure common paths for dev tools
        // (Windows uses system PATH from the parent process)
    }

    spawn_log_reader(child.stdout.take(), "backend");
    spawn_log_reader(child.stderr.take(), "backend");

    Ok(child)
}

fn verify_desktop_frontend(client: &reqwest::blocking::Client) -> Result<(), String> {
    let resp = client
        .get(APP_HOME_URL)
        .send()
        .map_err(|err| err.to_string())?;
    if !resp.status().is_success() {
        return Err(format!(
            "获客界面不可用 (HTTP {})。请查看日志: {}",
            resp.status(),
            desktop_log_hint()
        ));
    }
    let content_type = resp
        .headers()
        .get(reqwest::header::CONTENT_TYPE)
        .and_then(|value| value.to_str().ok())
        .unwrap_or("");
    if !content_type.contains("text/html") {
        return Err(format!(
            "端口 {DESKTOP_PORT} 未托管桌面前端（可能连到了开发 API 或其它服务）。\n\
             请关闭占用该端口的进程后重开应用。"
        ));
    }
    Ok(())
}

fn wait_backend_ready(timeout: Duration, child: &mut Child) -> Result<(), String> {
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .map_err(|err| err.to_string())?;
    let deadline = Instant::now() + timeout;
    let log_hint = desktop_log_hint();

    while Instant::now() < deadline {
        if let Ok(resp) = client.get(HEALTH_URL).send() {
            if resp.status().is_success() && verify_desktop_frontend(&client).is_ok() {
                return Ok(());
            }
        }
        if let Ok(Some(status)) = child.try_wait() {
            return Err(format!(
                "后端进程异常退出 (code={status})。\n日志: {log_hint}"
            ));
        }
        thread::sleep(Duration::from_millis(500));
    }

    Err(format!(
        "后端启动超时。请检查 Google Chrome 是否可用，并查看日志:\n{log_hint}"
    ))
}

fn stop_backend(state: &ServiceState) {
    let mut guard = state.backend.lock().expect("backend lock");
    if let Some(mut child) = guard.take() {
        let _ = child.kill();
        let _ = child.wait();
    }
}

fn show_startup_error(app: &AppHandle, message: &str) {
    let html = format!(
        r#"document.open();document.write(`<!doctype html><html><head><meta charset="utf-8"><title>启动失败</title>
        <style>body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;padding:32px;line-height:1.6;color:#222}}
        h1{{color:#c0392b}}pre{{white-space:pre-wrap;background:#f6f6f6;padding:16px;border-radius:8px}}</style></head>
        <body><h1>获客平台启动失败</h1><pre>{message}</pre>
        <p>排查：1) 安装 Google Chrome  2) 查看日志目录</p></body></html>`);document.close();"#
    );
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.eval(&html);
    }
}

fn open_app_home(app: &AppHandle) -> Result<(), String> {
    let main = app
        .get_webview_window("main")
        .ok_or_else(|| "主窗口不存在".to_string())?;
    let parsed = APP_HOME_URL
        .parse()
        .map_err(|err| format!("invalid url: {err}"))?;
    main.navigate(parsed)
        .map_err(|err| format!("打开获客首页失败: {err}"))?;
    Ok(())
}

fn bootstrap(app: &AppHandle) -> Result<(), String> {
    let root = repo_root(app)?;
    log::info!("Huoke root: {}", root.display());

    let mut backend = start_backend(&root)?;
    wait_backend_ready(Duration::from_secs(120), &mut backend)?;

    app.state::<ServiceState>()
        .backend
        .lock()
        .expect("backend lock")
        .replace(backend);

    open_app_home(app)?;
    log::info!("Huoke backend ready at {APP_HOME_URL}");
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(
            tauri_plugin_log::Builder::default()
                .level(log::LevelFilter::Info)
                .build(),
        )
        .manage(ServiceState {
            backend: Mutex::new(None),
        })
        .setup(|app| {
            let handle = app.handle().clone();
            match bootstrap(&handle) {
                Ok(()) => {}
                Err(err) => {
                    log::error!("bootstrap failed: {err}");
                    show_startup_error(&handle, &err);
                }
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                stop_backend(&*app.state::<ServiceState>());
                return;
            }

            if let RunEvent::WindowEvent {
                label,
                event: WindowEvent::CloseRequested { .. },
                ..
            } = event
            {
                if label == "main" {
                    stop_backend(&*app.state::<ServiceState>());
                }
            }
        });
}
