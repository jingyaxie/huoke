use std::io::{BufRead, BufReader, Read};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager, RunEvent, State, WindowEvent};

const HEALTH_URL: &str = "http://127.0.0.1:8000/api/health";
const APP_HOME_URL: &str = "http://127.0.0.1:8000/auto-tasks";

struct ServiceState {
    backend: Mutex<Option<Child>>,
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

    start_mysql(&root)?;
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
