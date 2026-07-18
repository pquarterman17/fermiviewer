"""FermiViewer offline installer — run this ON the target (air-gapped) machine.

    Windows:      py install.py        (or: python install.py)
    macOS/Linux:  python3 install.py

Creates a private virtual environment (.venv) next to this file and
installs FermiViewer plus all dependencies from the bundled wheelhouse/
directory. Nothing is downloaded — no internet access is needed — and
nothing outside this folder is touched. Re-running is safe (upgrades in
place). Uninstall = delete this folder.

After install, launch with the generated FermiViewer.bat (Windows) or
./fermiviewer (macOS/Linux).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import venv
from pathlib import Path

HERE = Path(__file__).resolve().parent

# lab-PC consoles are often strict cp1252; never let an unencodable
# character (e.g. a non-ASCII username in a printed path) kill an install
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")


def _die(msg: str) -> None:
    raise SystemExit(f"\nERROR: {msg}\n")


def _run(cmd: list[str]) -> None:
    print(f"  $ {' '.join(cmd)}")
    r = subprocess.run(cmd)
    if r.returncode != 0:
        _die(f"command failed (exit {r.returncode}): {cmd[0]}")


def _load_info() -> dict:
    p = HERE / "bundle-info.json"
    if not p.is_file():
        _die("bundle-info.json not found next to install.py -- run this script "
             "from inside the extracted fv-offline folder.")
    with open(p, encoding="utf-8") as f:
        info: dict = json.load(f)
    return info


def _check_environment(info: dict) -> None:
    this_os = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    if this_os != info["os"]:
        _die(f"this bundle contains {info['os']} packages but you are on {this_os} -- "
             f"download the fv-offline-{this_os}-*.zip bundle instead.")
    if info["arch"] == "x64" and sys.maxsize <= 2**32:
        _die("this bundle contains 64-bit packages but you are running a 32-bit "
             "Python -- install a 64-bit Python and re-run.")
    ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    covered = info["python_versions"]
    if ver not in covered:
        hint = ("py -3.13 install.py" if sys.platform == "win32"
                else "python3.13 install.py")
        _die(f"you are running Python {ver}, but this bundle covers "
             f"{', '.join(covered)}.\n"
             f"Either re-run with a covered version (e.g. `{hint}`) or install "
             "one from python.org -- the full installer works without internet.")


def _venv_python(venv_dir: Path) -> Path:
    sub = ("Scripts", "python.exe") if os.name == "nt" else ("bin", "python")
    return venv_dir.joinpath(*sub)


def _create_venv(venv_dir: Path, wheelhouse: Path) -> Path:
    py = _venv_python(venv_dir)
    if py.is_file():
        print(f"reusing existing environment: {venv_dir}")
        return py
    print(f"creating environment: {venv_dir}")
    try:
        venv.EnvBuilder(with_pip=True, symlinks=(os.name != "nt")).create(venv_dir)
    except Exception as e:  # ensurepip missing (Debian/Ubuntu system python)
        print(f"note: venv-with-pip failed ({e}); bootstrapping pip from the wheelhouse")
        venv.EnvBuilder(with_pip=False, clear=True,
                        symlinks=(os.name != "nt")).create(venv_dir)
        pips = sorted(wheelhouse.glob("pip-*.whl"))
        if not pips:
            _die("the environment has no pip and the wheelhouse carries no pip "
                 "wheel -- rebuild the bundle with tools/offline/make_bundle.py.")
        # run pip straight out of its own wheel (zipimport) to install itself
        _run([str(py), str(pips[-1]) + os.sep + "pip", "install",
              "--no-index", "--find-links", str(wheelhouse), "pip"])
    if not py.is_file():
        _die(f"virtual environment creation failed -- no interpreter at {py}")
    return py


def _write_launchers(target: Path, venv_dir: Path) -> list[Path]:
    made = []
    if os.name == "nt":
        bat = target / "FermiViewer.bat"
        bat.write_text(
            "@echo off\r\n"
            f"\"{venv_dir}\\Scripts\\fv.exe\" %*\r\n",
            encoding="ascii",
        )
        made.append(bat)
    else:
        sh = target / "fermiviewer"
        sh.write_text(
            "#!/bin/sh\n"
            f'exec "{venv_dir}/bin/fv" "$@"\n',
            encoding="ascii",
        )
        sh.chmod(0o755)
        made.append(sh)
    return made


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Install FermiViewer from the bundled wheelhouse (no internet needed).")
    ap.add_argument("--dir", default=str(HERE), metavar="DIR",
                    help="where to put .venv and the launcher (default: this folder)")
    args = ap.parse_args()

    info = _load_info()
    _check_environment(info)

    wheelhouse = HERE / "wheelhouse"
    if not wheelhouse.is_dir():
        _die("wheelhouse/ not found next to install.py -- extract the full zip "
             "before running.")

    target = Path(args.dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    venv_dir = target / ".venv"
    if os.name == "nt" and len(str(target)) > 140:
        # deep site-packages paths (numpy's dist-info) can exceed MAX_PATH
        print("WARNING: this folder's path is quite long; Windows installs can")
        print("         fail with 'filename too long'. If that happens, extract")
        print("         to a shorter path (e.g. C:\\FermiViewer) and re-run.")

    py = _create_venv(venv_dir, wheelhouse)
    base = [str(py), "-m", "pip", "install", "--no-index",
            "--find-links", str(wheelhouse)]
    if any(wheelhouse.glob("pip-*.whl")):
        # a current pip avoids old-ensurepip metadata quirks; best-effort
        subprocess.run(base + ["--upgrade", "--quiet", "pip"])
    _run(base + ["--upgrade", "fermiviewer"])

    check = subprocess.run(
        [str(py), "-c", "import fermiviewer; print(fermiviewer.__version__)"],
        capture_output=True, text=True)
    if check.returncode != 0:
        _die(f"install verification failed:\n{check.stderr}")
    version = check.stdout.strip()

    launchers = _write_launchers(target, venv_dir)
    print(f"\nFermiViewer {version} installed.")
    print("Launch it with:")
    for launcher in launchers:
        print(f"  {launcher}")
    print("(starts the app at http://127.0.0.1:8000 and opens your browser;")
    print(" it exits on its own when the last tab closes)")


if __name__ == "__main__":
    main()
