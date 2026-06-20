// FermiViewer desktop shell (handoff §11 option A): Tauri 2 window on
// the FastAPI server, spawned from the repo venv and killed with the
// window. The window first shows a bundled loading splash and only
// navigates to the live app once /api/health answers, so a slow server
// start (cold numpy/scipy import, first-run AV scan) never leaves the
// user staring at a "can't reach this page" error that won't retry.

#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

use std::io::{Read, Write};
use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::Manager;

struct ServerProc(Mutex<Option<Child>>);

const ADDR: &str = "127.0.0.1:8000";
const APP_URL: &str = "http://127.0.0.1:8000";

fn repo_root() -> PathBuf {
    // src-tauri/ lives one level under the repo root
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("src-tauri has a parent")
        .to_path_buf()
}

fn spawn_server(repo: &PathBuf) -> std::io::Result<Child> {
    // 1) installed app: the PyInstaller sidecar ships as a resource
    //    next to the shell exe (<install>/fv-server/fv-server.exe)
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            for cand in [
                dir.join("fv-server").join("fv-server.exe"),
                dir.join("resources").join("fv-server").join("fv-server.exe"),
            ] {
                if cand.is_file() {
                    let mut cmd = Command::new(&cand);
                    cmd.args(["--no-browser", "--no-auto-shutdown"]);
                    hide_console(&mut cmd);
                    return cmd.spawn();
                }
            }
        }
    }
    // 2) dev fallback: repo venv python directly (not the fv.exe
    //    launcher) so kill() reaches uvicorn itself rather than
    //    orphaning a grandchild interpreter
    let python = repo.join(".venv").join("Scripts").join("python.exe");
    let mut cmd = Command::new(python);
    cmd.args(["-m", "fermiviewer", "--no-browser", "--no-auto-shutdown"])
        .current_dir(repo);
    hide_console(&mut cmd);
    cmd.spawn()
}

#[cfg(target_os = "windows")]
fn hide_console(cmd: &mut Command) {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    cmd.creation_flags(CREATE_NO_WINDOW);
}

#[cfg(not(target_os = "windows"))]
fn hide_console(_cmd: &mut Command) {}

/// One HTTP GET /api/health attempt — distinguishes *our* server (200 +
/// a `"status"` JSON body) from a foreign app that merely holds the port.
fn http_health_ok() -> bool {
    let addr = match ADDR.parse() {
        Ok(a) => a,
        Err(_) => return false,
    };
    let Ok(mut stream) = TcpStream::connect_timeout(&addr, Duration::from_millis(500)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(800)));
    let req = b"GET /api/health HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n";
    if stream.write_all(req).is_err() {
        return false;
    }
    let mut buf = String::new();
    let _ = stream.read_to_string(&mut buf);
    buf.contains(" 200") && buf.contains("\"status\"")
}

/// Poll /api/health until it answers or the timeout elapses.
fn wait_for_health(timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if http_health_ok() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(300));
    }
    false
}

fn kill_server(app: &tauri::AppHandle) {
    if let Some(state) = app.try_state::<ServerProc>() {
        if let Ok(mut guard) = state.0.lock() {
            if let Some(mut child) = guard.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
}

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            let repo = repo_root();
            // a dev/leftover server may already own the port — reuse it
            let already = wait_for_health(Duration::from_millis(800));
            let child = if already {
                None
            } else {
                Some(spawn_server(&repo)?)
            };
            app.manage(ServerProc(Mutex::new(child)));

            // The window is already showing the bundled splash. Wait for
            // the server off the UI thread, then navigate to the live app
            // (or surface a clear error if it never comes up).
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let ok = already || wait_for_health(Duration::from_secs(60));
                if let Some(win) = handle.get_webview_window("main") {
                    if ok {
                        if let Ok(url) = APP_URL.parse() {
                            let _ = win.navigate(url);
                        }
                    } else {
                        let _ = win.eval(
                            "window.__fvError && window.__fvError('FermiViewer \
                             could not reach its local server on port 8000. \
                             Another program may be using the port, or your \
                             antivirus may be scanning the first launch. Close \
                             other copies and try again.')",
                        );
                    }
                }
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if matches!(event, tauri::WindowEvent::CloseRequested { .. }) {
                kill_server(window.app_handle());
            }
        })
        .build(tauri::generate_context!())
        .expect("error building the tauri application")
        .run(|app, event| {
            if matches!(event, tauri::RunEvent::Exit) {
                kill_server(app);
            }
        });
}
