use std::io::{BufRead, BufReader, Read};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager, RunEvent, WindowEvent};

const DESKTOP_PORT: u16 = 18765;
const HEALTH_URL: &str = "http://127.0.0.1:18765/api/health";
const APP_HOME_URL: &str = "http://127.0.0.1:18765/cloud/dashboard";
const BACKEND_LOG_CAP: usize = 120;

struct ServiceState {
    backend: Mutex<Option<Child>>,
}

struct BackendLogState {
    lines: Mutex<Vec<String>>,
}

impl BackendLogState {
    fn push_line(&self, line: String) {
        let mut guard = self.lines.lock().expect("backend log lock");
        guard.push(line);
        if guard.len() > BACKEND_LOG_CAP {
            let drain = guard.len() - BACKEND_LOG_CAP;
            guard.drain(0..drain);
        }
    }

    fn tail(&self, max_lines: usize) -> String {
        let guard = self.lines.lock().expect("backend log lock");
        if guard.is_empty() {
            return String::new();
        }
        let start = guard.len().saturating_sub(max_lines);
        guard[start..].join("\n")
    }
}

fn backend_script_name() -> &'static str {
    if cfg!(windows) {
        "desktop-run-backend.ps1"
    } else {
        "desktop-run-backend.sh"
    }
}

fn normalize_path(path: &Path) -> PathBuf {
    let text = path.to_string_lossy();
    if let Some(stripped) = text.strip_prefix(r"\\?\") {
        return PathBuf::from(stripped);
    }
    path.to_path_buf()
}

fn desktop_log_hint() -> String {
    if cfg!(windows) {
        if let Ok(app_data) = std::env::var("APPDATA") {
            return format!(
                r"{app_data}\com.huoke.desktop\logs\desktop-backend.log"
            );
        }
        return r"%APPDATA%\com.huoke.desktop\logs\desktop-backend.log".into();
    }
    if cfg!(target_os = "macos") {
        return "~/Library/Application Support/com.huoke.desktop/logs/desktop-backend.log".into();
    }
    "~/.local/share/huoke/logs/desktop-backend.log".into()
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

fn find_bundle_dir(base: &Path) -> Option<PathBuf> {
    let direct = [
        base.join("desktop/bundle"),
        base.join("bundle"),
    ];
    for dir in direct {
        if dir.join("runtime").is_dir() {
            return Some(dir);
        }
    }

    let mut queue = vec![base.to_path_buf()];
    while let Some(current) = queue.pop() {
        if current.ends_with("desktop/bundle") || current.ends_with("bundle") {
            if current.join("runtime").is_dir() {
                return Some(current);
            }
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
        let path = normalize_path(&PathBuf::from(root));
        if let Some(found) = find_launch_root(&path) {
            return Ok(found);
        }
    }

    let resource_dir = normalize_path(
        &app
            .path()
            .resource_dir()
            .map_err(|err| err.to_string())?,
    );
    if let Some(found) = find_launch_root(&resource_dir) {
        return Ok(found);
    }

    if cfg!(windows) {
        if let Ok(exe_dir) = app.path().executable_dir() {
            let exe_dir = normalize_path(&exe_dir);
            if let Some(found) = find_launch_root(&exe_dir) {
                return Ok(found);
            }
        }
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

fn resolve_bundle_dir(root: &Path) -> Result<PathBuf, String> {
    find_bundle_dir(root).ok_or_else(|| {
        format!(
            "未找到桌面 bundle（缺少 runtime 目录）。HUOKE_ROOT={}",
            root.display()
        )
    })
}

fn windows_data_dir() -> Option<String> {
    if !cfg!(windows) {
        return None;
    }
    std::env::var("APPDATA")
        .ok()
        .map(|app_data| format!(r"{app_data}\com.huoke.desktop"))
}

fn spawn_log_reader<R>(stream: Option<R>, prefix: &'static str, log_state: Option<Arc<BackendLogState>>)
where
    R: Read + Send + 'static,
{
    if let Some(stream) = stream {
        thread::spawn(move || {
            let reader = BufReader::new(stream);
            for line in reader.lines().map_while(Result::ok) {
                log::info!("[{prefix}] {line}");
                if let Some(state) = &log_state {
                    state.push_line(line);
                }
            }
        });
    }
}

fn start_backend(root: &PathBuf, log_state: Arc<BackendLogState>) -> Result<Child, String> {
    let root = normalize_path(root);
    let script = root.join("scripts").join(backend_script_name());
    if !script.is_file() {
        return Err(format!("缺少脚本: {}", script.display()));
    }

    let bundle_dir = resolve_bundle_dir(&root)?;

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

    if let Some(data_dir) = windows_data_dir() {
        command.env("HUOKE_DATA_DIR", data_dir);
    }

    let mut child = command
        .current_dir(&root)
        .env("HUOKE_ROOT", &root)
        .env("HUOKE_BUNDLE_DIR", &bundle_dir)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|err| format!("启动后端失败: {err}"))?;

    spawn_log_reader(child.stdout.take(), "backend", Some(Arc::clone(&log_state)));
    spawn_log_reader(child.stderr.take(), "backend", Some(log_state));

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

fn format_backend_failure(base: &str, log_state: &BackendLogState) -> String {
    let tail = log_state.tail(30);
    if tail.is_empty() {
        return base.to_string();
    }
    format!("{base}\n\n后端输出（最近 30 行）:\n{tail}")
}

fn wait_backend_ready(
    timeout: Duration,
    child: &mut Child,
    log_state: &BackendLogState,
) -> Result<(), String> {
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
            let code = status
                .code()
                .map(|c| c.to_string())
                .unwrap_or_else(|| status.to_string());
            let base = format!("后端进程异常退出 (code={code})。\n日志: {log_hint}");
            return Err(format_backend_failure(&base, log_state));
        }
        thread::sleep(Duration::from_millis(500));
    }

    let base = format!("后端启动超时。请查看日志:\n{log_hint}");
    Err(format_backend_failure(&base, log_state))
}

fn stop_backend(state: &ServiceState) {
    let mut guard = state.backend.lock().expect("backend lock");
    if let Some(mut child) = guard.take() {
        let _ = child.kill();
        let _ = child.wait();
    }
}

fn show_startup_error(app: &AppHandle, message: &str) {
    let log_hint = desktop_log_hint();
    let html = format!(
        r#"document.open();document.write(`<!doctype html><html><head><meta charset="utf-8"><title>启动失败</title>
        <style>body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;padding:32px;line-height:1.6;color:#222}}
        h1{{color:#c0392b}}pre{{white-space:pre-wrap;background:#f6f6f6;padding:16px;border-radius:8px}}</style></head>
        <body><h1>获客平台启动失败</h1><pre>{message}</pre>
        <p>日志: {log_hint}</p>
        <p>应用日志中搜索 [backend] 行；端口 {DESKTOP_PORT} 未被占用后重试。</p></body></html>`);document.close();"#
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

fn bootstrap(app: &AppHandle, log_state: Arc<BackendLogState>) -> Result<(), String> {
    let root = repo_root(app)?;
    log::info!("Huoke root: {}", root.display());

    let mut backend = start_backend(&root, Arc::clone(&log_state))?;
    wait_backend_ready(Duration::from_secs(120), &mut backend, &log_state)?;

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
        .manage(Arc::new(BackendLogState {
            lines: Mutex::new(Vec::new()),
        }))
        .setup(|app| {
            let handle = app.handle().clone();
            let log_state = app.state::<Arc<BackendLogState>>();
            match bootstrap(&handle, Arc::clone(&log_state)) {
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
