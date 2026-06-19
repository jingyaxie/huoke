use std::fs::OpenOptions;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
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

struct BackendProcess {
    child: Child,
    log_readers: Vec<JoinHandle<()>>,
}

fn launch_marker_name() -> &'static str {
    if cfg!(windows) {
        "desktop_run_backend.py"
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

fn display_path(path: &Path) -> String {
    path.to_string_lossy().replace('\\', "/")
}

fn resolve_app_log_file(app: &AppHandle) -> Result<PathBuf, String> {
    let log_dir = app.path().app_log_dir().map_err(|err| err.to_string())?;
    std::fs::create_dir_all(&log_dir).map_err(|err| err.to_string())?;
    let file_name = app
        .config()
        .product_name
        .clone()
        .unwrap_or_else(|| "huoke".to_string());
    Ok(log_dir.join(format!("{file_name}.log")))
}

fn desktop_log_hint(app: &AppHandle) -> String {
    resolve_app_log_file(app)
        .map(|path| display_path(&path))
        .unwrap_or_else(|_| {
            if cfg!(windows) {
                "%LOCALAPPDATA%/com.huoke.desktop/logs/盈小蚁客户前端.log".into()
            } else if cfg!(target_os = "macos") {
                "~/Library/Logs/com.huoke.desktop/盈小蚁客户前端.log".into()
            } else {
                "~/.local/share/com.huoke.desktop/logs/盈小蚁客户前端.log".into()
            }
        })
}

fn append_unified_log(log_file: &Path, line: &str) {
    let Ok(mut file) = OpenOptions::new().create(true).append(true).open(log_file) else {
        return;
    };
    let _ = writeln!(file, "{line}");
}

fn find_launch_root(base: &Path) -> Option<PathBuf> {
    let backend_script = PathBuf::from("scripts").join(launch_marker_name());
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

fn spawn_log_reader<R>(
    stream: Option<R>,
    log_file: Arc<PathBuf>,
    log_state: Arc<BackendLogState>,
) -> Option<JoinHandle<()>>
where
    R: std::io::Read + Send + 'static,
{
    stream.map(|stream| {
        thread::spawn(move || {
            let reader = BufReader::new(stream);
            for line in reader.lines().map_while(Result::ok) {
                append_unified_log(&log_file, &line);
                log::info!("[backend] {line}");
                log_state.push_line(line);
            }
        })
    })
}

fn drain_log_readers(handles: Vec<JoinHandle<()>>) {
    for handle in handles {
        let _ = handle.join();
    }
}

#[cfg(windows)]
fn find_windows_python_exe(bundle_dir: &Path, root: &Path) -> Result<PathBuf, String> {
    for rel in [
        "runtime/python/python.exe",
        "runtime/.venv/Scripts/python.exe",
    ] {
        let candidate = bundle_dir.join(rel);
        if candidate.is_file() {
            return Ok(candidate);
        }
    }
    let dev = root.join("backend/.venv/Scripts/python.exe");
    if dev.is_file() {
        return Ok(dev);
    }
    Err(format!(
        "Python runtime not found (bundle={})",
        bundle_dir.display()
    ))
}

#[cfg_attr(not(windows), allow(unused_variables))]
fn build_backend_command(root: &Path, bundle_dir: &Path) -> Result<Command, String> {
    #[cfg(windows)]
    {
        let python = find_windows_python_exe(bundle_dir, root)?;
        let script = root.join("scripts").join("desktop_run_backend.py");
        if !script.is_file() {
            return Err(format!("缺少脚本: {}", script.display()));
        }
        let mut cmd = Command::new(python);
        cmd.arg(script).arg("--port").arg(DESKTOP_PORT.to_string());
        return Ok(cmd);
    }
    #[cfg(not(windows))]
    {
        let script = root.join("scripts").join("desktop-run-backend.sh");
        if !script.is_file() {
            return Err(format!("缺少脚本: {}", script.display()));
        }
        let mut cmd = Command::new("/bin/bash");
        cmd.arg(script);
        Ok(cmd)
    }
}

fn apply_backend_command_env(
    command: &mut Command,
    root: &Path,
    bundle_dir: &Path,
    log_file: &Path,
) {
    if let Some(data_dir) = windows_data_dir() {
        command.env("HUOKE_DATA_DIR", data_dir);
    }
    command.env("HUOKE_LOG_FILE", log_file);
    command
        .current_dir(root)
        .env("HUOKE_ROOT", root)
        .env("HUOKE_BUNDLE_DIR", bundle_dir)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
}

#[cfg(windows)]
fn hide_backend_console(command: &mut Command) {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x08000000;
    command.creation_flags(CREATE_NO_WINDOW);
}

#[cfg(not(windows))]
fn hide_backend_console(_command: &mut Command) {}

fn start_backend(
    root: &PathBuf,
    log_file: &Path,
    log_state: Arc<BackendLogState>,
) -> Result<BackendProcess, String> {
    let root = normalize_path(root);
    let bundle_dir = resolve_bundle_dir(&root)?;
    let log_file = Arc::new(log_file.to_path_buf());

    let mut command = build_backend_command(&root, &bundle_dir)?;
    apply_backend_command_env(&mut command, &root, &bundle_dir, log_file.as_path());
    hide_backend_console(&mut command);

    let mut child = command
        .spawn()
        .map_err(|err| format!("启动后端失败: {err}"))?;

    let mut log_readers = Vec::new();
    if let Some(handle) = spawn_log_reader(
        child.stdout.take(),
        Arc::clone(&log_file),
        Arc::clone(&log_state),
    ) {
        log_readers.push(handle);
    }
    if let Some(handle) = spawn_log_reader(child.stderr.take(), log_file, log_state) {
        log_readers.push(handle);
    }

    Ok(BackendProcess { child, log_readers })
}

fn verify_desktop_frontend(
    client: &reqwest::blocking::Client,
    log_hint: &str,
) -> Result<(), String> {
    let resp = client
        .get(APP_HOME_URL)
        .send()
        .map_err(|err| err.to_string())?;
    if !resp.status().is_success() {
        return Err(format!(
            "获客界面不可用 (HTTP {})。请查看日志: {}",
            resp.status(),
            log_hint
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
    let tail = log_state.tail(80);
    if tail.is_empty() {
        return base.to_string();
    }
    format!("{base}\n\n后端输出（最近 80 行）:\n{tail}")
}

fn wait_backend_ready(
    timeout: Duration,
    backend: &mut BackendProcess,
    log_state: &BackendLogState,
    log_hint: &str,
) -> Result<(), String> {
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .map_err(|err| err.to_string())?;
    let deadline = Instant::now() + timeout;

    loop {
        if Instant::now() >= deadline {
            drain_log_readers(std::mem::take(&mut backend.log_readers));
            let base = format!("后端启动超时。请查看日志:\n{log_hint}");
            return Err(format_backend_failure(&base, log_state));
        }

        if let Ok(resp) = client.get(HEALTH_URL).send() {
            if resp.status().is_success() && verify_desktop_frontend(&client, log_hint).is_ok() {
                return Ok(());
            }
        }

        if let Ok(Some(status)) = backend.child.try_wait() {
            drain_log_readers(std::mem::take(&mut backend.log_readers));
            let code = status
                .code()
                .map(|c| c.to_string())
                .unwrap_or_else(|| status.to_string());
            let base = format!("后端进程异常退出 (code={code})。\n日志: {log_hint}");
            return Err(format_backend_failure(&base, log_state));
        }

        thread::sleep(Duration::from_millis(500));
    }
}

fn stop_backend(state: &ServiceState) {
    let mut guard = state.backend.lock().expect("backend lock");
    if let Some(mut child) = guard.take() {
        let _ = child.kill();
        let _ = child.wait();
    }
}

fn with_main_thread<R, F>(app: &AppHandle, f: F) -> Result<R, String>
where
    F: FnOnce(&AppHandle) -> Result<R, String> + Send + 'static,
    R: Send + 'static,
{
    let (tx, rx) = std::sync::mpsc::channel();
    let handle = app.clone();
    app.run_on_main_thread(move || {
        let _ = tx.send(f(&handle));
    })
    .map_err(|err| err.to_string())?;
    rx.recv()
        .map_err(|_| "主线程任务未完成".to_string())?
}

fn show_startup_loading(app: &AppHandle) {
    let html = r#"document.open();document.write('<!doctype html><html><head><meta charset="utf-8"><title>启动中</title>
        <style>body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;padding:48px;text-align:center;color:#444}
        h1{font-size:22px;font-weight:600}p{margin-top:12px;color:#666}</style></head>
        <body><h1>正在启动获客平台…</h1><p>首次启动可能需要 1-2 分钟，请稍候。</p></body></html>');document.close();"#;
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.eval(html);
    }
}

fn show_startup_error(app: &AppHandle, message: &str) {
    let log_hint = desktop_log_hint(app);
    let message_js = serde_json::to_string(message).unwrap_or_else(|_| "\"启动失败\"".into());
    let log_hint_js = serde_json::to_string(&log_hint).unwrap_or_else(|_| "\"\"".into());
    let html = format!(
        r#"document.open();document.write('<!doctype html><html><head><meta charset="utf-8"><title>启动失败</title>
        <style>body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;padding:32px;line-height:1.6;color:#222}}
        h1{{color:#c0392b}}pre{{white-space:pre-wrap;background:#f6f6f6;padding:16px;border-radius:8px;font-size:13px}}</style></head>
        <body><h1>获客平台启动失败</h1><pre>' + {message_js} + '</pre>
        <p>日志文件: ' + {log_hint_js} + '</p>
        <p>请打开上述日志，搜索 <code>[backend]</code> 或 <code>FATAL</code> 查看详情；确认端口 {DESKTOP_PORT} 未被占用后重试。</p></body></html>');document.close();"#
    );
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.eval(&html);
    }
}

fn open_app_home(app: &AppHandle) -> Result<(), String> {
    let main = app
        .get_webview_window("main")
        .ok_or_else(|| "主窗口不存在".to_string())?;
    main.eval("window.location.reload();")
        .map_err(|err| format!("打开获客首页失败: {err}"))?;
    Ok(())
}

fn bootstrap(app: &AppHandle, log_state: Arc<BackendLogState>) -> Result<(), String> {
    with_main_thread(app, |app| {
        show_startup_loading(app);
        Ok(())
    })?;

    let root = repo_root(app)?;
    let log_file = resolve_app_log_file(app)?;
    let log_hint = display_path(&log_file);
    log::info!("Huoke root: {}", root.display());
    log::info!("Unified log file: {log_hint}");

    let mut backend = start_backend(&root, &log_file, Arc::clone(&log_state))?;
    wait_backend_ready(
        Duration::from_secs(120),
        &mut backend,
        &log_state,
        &log_hint,
    )?;

    // Do not join log reader threads here: they block until backend stdout/stderr
    // close, which only happens when the process exits — leaving the UI on about:blank.
    let BackendProcess { child, log_readers: _ } = backend;

    app.state::<ServiceState>()
        .backend
        .lock()
        .expect("backend lock")
        .replace(child);

    with_main_thread(app, open_app_home)?;
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
            let log_state = {
                let state = app.state::<Arc<BackendLogState>>();
                Arc::clone(&state)
            };
            std::thread::spawn(move || match bootstrap(&handle, log_state) {
                Ok(()) => {}
                Err(err) => {
                    log::error!("bootstrap failed: {err}");
                    let app = handle.clone();
                    let message = err;
                    let _ = handle.run_on_main_thread(move || show_startup_error(&app, &message));
                }
            });
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
