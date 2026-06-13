use std::io::{BufRead, BufReader, Read};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use tauri::{
    AppHandle, Emitter, LogicalPosition, LogicalSize, Manager, RunEvent, State, WebviewUrl,
    WebviewWindow, WebviewWindowBuilder, WindowEvent,
};

const HEALTH_URL: &str = "http://127.0.0.1:8000/api/health";
const APP_URL: &str = "http://127.0.0.1:8000";
const APP_HOME_URL: &str = "http://127.0.0.1:8000/test";
const PORTAL_URL: &str = "https://www.tanjiyunai.com/customer/platform-bindings";
const BROWSER_USER_AGENT: &str = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.4 Safari/605.1.15";
const FOOTER_HEIGHT: f64 = 52.0;
const PORTAL_DATA_STORE_ID: [u8; 16] = [
    0x48, 0x75, 0x6f, 0x6b, 0x65, 0x2d, 0x70, 0x6f, 0x72, 0x74, 0x61, 0x6c, 0x2d, 0x64, 0x73, 0x01,
];

struct ServiceState {
    backend: Mutex<Option<Child>>,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum ShellMode {
    Portal,
    App,
}

impl ShellMode {
    fn as_str(self) -> &'static str {
        match self {
            ShellMode::Portal => "portal",
            ShellMode::App => "app",
        }
    }
}

struct ShellState {
    mode: Mutex<ShellMode>,
}

fn find_launch_root(base: &PathBuf) -> Option<PathBuf> {
    let mut queue = vec![base.clone()];
    let backend_script = PathBuf::from("scripts/desktop-run-backend.sh");

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
    if let Some(found) = find_launch_root(&dev_root.to_path_buf()) {
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

fn start_mysql(root: &PathBuf) -> Result<(), String> {
    let script = root.join("scripts").join("desktop-run-mysql.sh");
    if !script.is_file() {
        return Err(format!("缺少脚本: {}", script.display()));
    }

    let status = Command::new("/bin/bash")
        .arg(script)
        .current_dir(root)
        .env("HUOKE_ROOT", root)
        .env(
            "PATH",
            "/usr/local/bin:/opt/homebrew/bin:/Applications/Docker.app/Contents/Resources/bin:/usr/bin:/bin",
        )
        .status()
        .map_err(|err| format!("启动 MySQL 失败: {err}"))?;

    if status.success() {
        Ok(())
    } else {
        Err(
            "MySQL 启动失败。请确认 Docker Desktop 已安装并正在运行。\n\
             日志: ~/Library/Application Support/com.huoke.desktop/logs/desktop-mysql.log"
                .into(),
        )
    }
}

fn start_backend(root: &PathBuf) -> Result<Child, String> {
    let script = root.join("scripts").join("desktop-run-backend.sh");
    if !script.is_file() {
        return Err(format!("缺少脚本: {}", script.display()));
    }

    let bundle_dir = if root.join("desktop/bundle").is_dir() {
        root.join("desktop/bundle")
    } else if root.join("bundle").is_dir() {
        root.join("bundle")
    } else {
        root.join("desktop/bundle")
    };

    let mut child = Command::new("/bin/bash")
        .arg(script)
        .current_dir(root)
        .env("HUOKE_ROOT", root)
        .env("HUOKE_BUNDLE_DIR", bundle_dir)
        .env(
            "PATH",
            "/usr/local/bin:/opt/homebrew/bin:/Applications/Docker.app/Contents/Resources/bin:/usr/bin:/bin",
        )
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|err| format!("启动后端失败: {err}"))?;

    spawn_log_reader(child.stdout.take(), "backend");
    spawn_log_reader(child.stderr.take(), "backend");

    Ok(child)
}

fn wait_backend_ready(timeout: Duration, child: &mut Child) -> Result<(), String> {
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .map_err(|err| err.to_string())?;
    let deadline = Instant::now() + timeout;

    while Instant::now() < deadline {
        if let Ok(resp) = client.get(HEALTH_URL).send() {
            if resp.status().is_success() {
                return Ok(());
            }
        }
        if let Ok(Some(status)) = child.try_wait() {
            return Err(format!(
                "后端进程异常退出 (code={status})。\n\
                 日志: ~/Library/Application Support/com.huoke.desktop/logs/desktop-backend.log"
            ));
        }
        thread::sleep(Duration::from_millis(500));
    }

    Err(
        "后端启动超时。请检查 Docker / Chrome 是否可用，并查看日志:\n\
         ~/Library/Application Support/com.huoke.desktop/logs/desktop-backend.log"
            .into(),
    )
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
        <style>body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;padding:32px;line-height:1.6;color:#222}}
        h1{{color:#c0392b}}pre{{white-space:pre-wrap;background:#f6f6f6;padding:16px;border-radius:8px}}</style></head>
        <body><h1>获客平台启动失败</h1><pre>{message}</pre>
        <p>排查：1) 打开 Docker Desktop  2) 安装 Google Chrome  3) 查看日志目录</p></body></html>`);document.close();"#
    );
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.eval(&html);
    }
}

fn sync_footer_geometry(main: &WebviewWindow, footer: &WebviewWindow) {
    let Ok(size) = main.inner_size() else {
        return;
    };

    let width = size.width as f64;
    let height = FOOTER_HEIGHT;
    let y = (size.height as f64 - height).max(0.0);

    let _ = footer.set_size(LogicalSize::new(width, height));
    let _ = footer.set_position(LogicalPosition::new(0.0, y));
}

fn sync_portal_geometry(main: &WebviewWindow, portal: &WebviewWindow) {
    let Ok(size) = main.inner_size() else {
        return;
    };

    let width = size.width as f64;
    let height = (size.height as f64 - FOOTER_HEIGHT).max(0.0);
    let _ = portal.set_size(LogicalSize::new(width, height));
    let _ = portal.set_position(LogicalPosition::new(0.0, 0.0));
}

fn sync_shell_layout(app: &AppHandle) {
    let Some(main) = app.get_webview_window("main") else {
        return;
    };
    if let Some(portal) = app.get_webview_window("portal") {
        sync_portal_geometry(&main, &portal);
    }
    if let Some(footer) = app.get_webview_window("shell-footer") {
        sync_footer_geometry(&main, &footer);
    }
}

fn ensure_portal_window(app: &AppHandle) -> Result<WebviewWindow, String> {
    if let Some(portal) = app.get_webview_window("portal") {
        if let Some(main) = app.get_webview_window("main") {
            sync_portal_geometry(&main, &portal);
        }
        return Ok(portal);
    }

    let main = app
        .get_webview_window("main")
        .ok_or_else(|| "主窗口不存在".to_string())?;
    let parsed = PORTAL_URL
        .parse()
        .map_err(|err| format!("invalid url: {err}"))?;

    let mut builder = WebviewWindowBuilder::new(app, "portal", WebviewUrl::External(parsed))
        .title("")
        .decorations(false)
        .user_agent(BROWSER_USER_AGENT)
        .incognito(false)
        .data_store_identifier(PORTAL_DATA_STORE_ID)
        .visible(false)
        .focused(false)
        .skip_taskbar(true);

    builder = builder
        .parent(&main)
        .map_err(|err| format!("创建 Portal 窗口失败: {err}"))?;

    let portal = builder
        .build()
        .map_err(|err| format!("创建 Portal 窗口失败: {err}"))?;

    sync_portal_geometry(&main, &portal);
    Ok(portal)
}

fn ensure_shell_footer(app: &AppHandle) -> Result<WebviewWindow, String> {
    if let Some(footer) = app.get_webview_window("shell-footer") {
        if let Some(main) = app.get_webview_window("main") {
            sync_footer_geometry(&main, &footer);
        }
        return Ok(footer);
    }

    let main = app
        .get_webview_window("main")
        .ok_or_else(|| "主窗口不存在".to_string())?;
    let footer_url = format!("{APP_URL}/shell-footer.html");
    let parsed = footer_url
        .parse()
        .map_err(|err| format!("invalid url: {err}"))?;

    let footer = WebviewWindowBuilder::new(app, "shell-footer", WebviewUrl::External(parsed))
        .parent(&main)
        .map_err(|err| format!("创建底部栏失败: {err}"))?
        .title("")
        .user_agent(BROWSER_USER_AGENT)
        .decorations(false)
        .always_on_top(true)
        .resizable(false)
        .skip_taskbar(true)
        .focused(false)
        .visible(true)
        .build()
        .map_err(|err| format!("创建底部栏失败: {err}"))?;

    sync_footer_geometry(&main, &footer);
    Ok(footer)
}

fn update_footer_mode(app: &AppHandle, mode: ShellMode) {
    if let Some(footer) = app.get_webview_window("shell-footer") {
        let mode_name = mode.as_str();
        let _ = footer.eval(format!(
            "if (typeof setShellMode === 'function') setShellMode('{mode_name}');"
        ));
    }
}

fn set_shell_mode(app: &AppHandle, shell: &ShellState, mode: ShellMode) -> Result<(), String> {
    {
        let mut guard = shell.mode.lock().expect("shell mode lock");
        *guard = mode;
    }

    let main = app
        .get_webview_window("main")
        .ok_or_else(|| "主窗口不存在".to_string())?;
    let portal = ensure_portal_window(app)?;

    match mode {
        ShellMode::Portal => {
            sync_portal_geometry(&main, &portal);
            portal
                .show()
                .map_err(|err| format!("显示 Portal 失败: {err}"))?;
            let _ = portal.set_focus();
        }
        ShellMode::App => {
            portal
                .hide()
                .map_err(|err| format!("隐藏 Portal 失败: {err}"))?;
            let parsed = APP_HOME_URL
                .parse()
                .map_err(|err| format!("invalid url: {err}"))?;
            main.navigate(parsed)
                .map_err(|err| format!("切换页面失败: {err}"))?;
            let _ = main.set_focus();
        }
    }

    sync_shell_layout(app);
    update_footer_mode(app, mode);
    let _ = app.emit("shell-mode-changed", mode.as_str());
    Ok(())
}

#[tauri::command]
fn shell_get_mode(shell: State<'_, ShellState>) -> Result<String, String> {
    let mode = shell.mode.lock().expect("shell mode lock");
    Ok(mode.as_str().to_string())
}

#[tauri::command]
fn shell_open_app(app: AppHandle, shell: State<'_, ShellState>) -> Result<(), String> {
    set_shell_mode(&app, &shell, ShellMode::App)
}

#[tauri::command]
fn shell_open_portal(app: AppHandle, shell: State<'_, ShellState>) -> Result<(), String> {
    set_shell_mode(&app, &shell, ShellMode::Portal)
}

fn bootstrap(app: &AppHandle) -> Result<(), String> {
    let root = repo_root(app)?;
    log::info!("Huoke root: {}", root.display());

    start_mysql(&root)?;
    let mut backend = start_backend(&root)?;
    wait_backend_ready(Duration::from_secs(120), &mut backend)?;

    app.state::<ServiceState>()
        .backend
        .lock()
        .expect("backend lock")
        .replace(backend);

    log::info!("Huoke backend ready at {APP_URL}");

    ensure_portal_window(app)?;
    ensure_shell_footer(app)?;
    set_shell_mode(app, &*app.state::<ShellState>(), ShellMode::Portal)?;

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
        .manage(ShellState {
            mode: Mutex::new(ShellMode::Portal),
        })
        .invoke_handler(tauri::generate_handler![
            shell_get_mode,
            shell_open_app,
            shell_open_portal
        ])
        .setup(|app| {
            if let Some(main) = app.get_webview_window("main") {
                let handle = app.handle().clone();
                main.on_window_event(move |event| {
                    if matches!(
                        event,
                        WindowEvent::Resized(_)
                            | WindowEvent::Moved(_)
                            | WindowEvent::ScaleFactorChanged { .. }
                    ) {
                        sync_shell_layout(&handle);
                    }
                });
            }

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
                    if let Some(portal) = app.get_webview_window("portal") {
                        let _ = portal.close();
                    }
                    if let Some(footer) = app.get_webview_window("shell-footer") {
                        let _ = footer.close();
                    }
                }
                stop_backend(&*app.state::<ServiceState>());
            }
        });
}
