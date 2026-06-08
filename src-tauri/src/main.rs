// FermiViewer desktop shell (handoff §11 option A): Tauri 2 window on
// the FastAPI server, spawned from the repo venv and killed with the
// window. The SPA is served by the backend, so the window just points
// at http://127.0.0.1:8000 once the health endpoint answers.

#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::Duration;

use tauri::Manager;

struct ServerProc(Mutex<Option<Child>>);

const ADDR: &str = "127.0.0.1:8000";

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

fn wait_for_server(timeout: Duration) -> bool {
    let deadline = std::time::Instant::now() + timeout;
    while std::time::Instant::now() < deadline {
        if TcpStream::connect_timeout(
            &ADDR.parse().expect("static addr parses"),
            Duration::from_millis(500),
        )
        .is_ok()
        {
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
            // a dev server may already own the port — reuse it
            let child = if wait_for_server(Duration::from_millis(700)) {
                None
            } else {
                let c = spawn_server(&repo)?;
                if !wait_for_server(Duration::from_secs(20)) {
                    eprintln!("fermiviewer server did not come up on {ADDR}");
                }
                Some(c)
            };
            app.manage(ServerProc(Mutex::new(child)));
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
