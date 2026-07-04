"""Build a self-contained offline install bundle (run on a CONNECTED machine).

The output zip contains everything an air-gapped machine needs to install
and run FermiViewer from source — no internet, Node, or compiler there:

    fv-offline/
      install.py          stdlib-only installer (creates .venv, installs)
      README-OFFLINE.md   target-machine instructions
      bundle-info.json    platform + Python coverage manifest
      requirements.txt    exact pinned versions (provenance / IT review)
      wheelhouse/         fermiviewer wheel (SPA baked in) + all deps

Usage, from the repo root (needs uv on PATH; uv fetches each covered
Python and runs pip natively under it, so requirement markers like
`numpy==2.2.6 ; python_full_version < '3.11'` resolve exactly as they
will on the target — `pip download --python-version` can't do that, it
retargets wheel tags but evaluates markers against the running Python):

    uv run python tools/offline/make_bundle.py
    uv run python tools/offline/make_bundle.py --out build/my-bundle.zip
    uv run python tools/offline/make_bundle.py --python-versions 3.12 3.13

Wheels are downloaded for the platform this script runs on — build the
Windows bundle on Windows, the macOS bundle on macOS, etc. (the release
workflow does all three; see .github/workflows/release.yml).
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

# Windows redirects stdout/stderr as strict cp1252 — never let a message
# containing a dependency's non-ASCII metadata kill a finished build
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")

# supported CPython minor versions to cover in the wheelhouse; must stay
# within pyproject's requires-python. More versions = bigger bundle but
# fewer "wrong Python" surprises on the target machine.
DEFAULT_PY_VERSIONS = ("3.10", "3.11", "3.12", "3.13", "3.14")


def _run(cmd: list[str], **kw: object) -> None:
    print(f"  $ {' '.join(cmd)}")
    r = subprocess.run(cmd, **kw)  # type: ignore[call-overload]
    if r.returncode != 0:
        raise SystemExit(f"command failed (exit {r.returncode}): {cmd[0]}")


def _platform_label() -> tuple[str, str]:
    os_name = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    mach = platform.machine().lower()
    arch = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(mach, mach)
    return os_name, arch


def _ensure_spa() -> None:
    """Make sure frontend/dist exists; build it if not (needs npm)."""
    dist = REPO / "frontend" / "dist"
    if (dist / "index.html").is_file():
        newest_src = max(
            (p.stat().st_mtime for p in (REPO / "frontend" / "src").rglob("*") if p.is_file()),
            default=0.0,
        )
        if newest_src > (dist / "index.html").stat().st_mtime:
            print("WARNING: frontend/dist is older than frontend/src -- the bundle")
            print("         will carry a stale SPA. Rebuild first: cd frontend && npm run build")
        return
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit(
            "frontend/dist not found and npm is not on PATH -- build the SPA "
            "once with: cd frontend && npm ci && npm run build"
        )
    print("frontend/dist missing -- building the SPA (npm ci && npm run build)")
    # npm is a .cmd shim on Windows; CreateProcess can't exec it directly
    prefix = ["cmd", "/c"] if sys.platform == "win32" else []
    _run(prefix + ["npm", "ci"], cwd=REPO / "frontend")
    _run(prefix + ["npm", "run", "build"], cwd=REPO / "frontend")


def _build_project_wheel(wheelhouse: Path) -> str:
    """uv build the fermiviewer wheel into the wheelhouse; verify the SPA
    got baked in (hatch_build.py) and return the version string."""
    _run(["uv", "build", "--wheel", "--out-dir", str(wheelhouse)], cwd=REPO)
    # uv build drops a `.gitignore` into --out-dir; keep the wheelhouse
    # wheels-only so it ships clean and the sdist scan below stays honest
    (wheelhouse / ".gitignore").unlink(missing_ok=True)
    wheels = sorted(wheelhouse.glob("fermiviewer-*.whl"))
    if not wheels:
        raise SystemExit("uv build produced no fermiviewer wheel")
    whl = wheels[-1]
    with zipfile.ZipFile(whl) as z:
        if "fermiviewer/_spa/index.html" not in z.namelist():
            raise SystemExit(
                f"{whl.name} does not contain the SPA (fermiviewer/_spa/) -- "
                "the offline bundle would be API-only. Is frontend/dist built?"
            )
    # fermiviewer-0.1.10-py3-none-any.whl → 0.1.10
    return whl.name.split("-")[1]


def _download_deps(wheelhouse: Path, py_versions: tuple[str, ...]) -> None:
    req = wheelhouse.parent / "requirements.txt"
    _run(
        [
            "uv", "export", "--frozen", "--no-dev", "--no-emit-project",
            "--no-hashes", "--format", "requirements-txt", "-o", str(req),
        ],
        cwd=REPO,
    )
    for v in py_versions:
        print(f"-- downloading dependency wheels for Python {v} --")
        # run pip UNDER the actual target interpreter (uv fetches it on
        # demand) so version markers evaluate for that version — see the
        # module docstring for why --python-version alone is not enough
        _run([
            "uv", "run", "--python", v, "--with", "pip", "--no-project",
            "python", "-m", "pip", "download", "-r", str(req),
            "--dest", str(wheelhouse), "--prefer-binary",
        ])
    # a current pip wheel (universal): lets install.py bootstrap/upgrade pip
    # on targets whose venv pip is ancient or whose python lacks ensurepip
    _run([
        "uv", "run", "--python", py_versions[-1], "--with", "pip", "--no-project",
        "python", "-m", "pip", "download", "pip",
        "--dest", str(wheelhouse), "--only-binary", ":all:",
    ])
    # a few deps publish no wheel at all (proxy_tools, via pywebview) and
    # arrive as sdists — build them into wheels HERE, on the connected
    # machine, under each covered interpreter, so the air-gapped target
    # never needs setuptools or a compiler. Pure packages yield one
    # py3-none-any wheel; a platform-specific sdist would surface as a
    # loud per-version build failure rather than a silent coverage gap.
    sdists = [
        p for p in wheelhouse.iterdir()
        if p.name.endswith((".tar.gz", ".tar.bz2", ".zip"))
    ]
    for sdist in sdists:
        print(f"-- building wheel from sdist: {sdist.name} --")
        for v in py_versions:
            _run([
                "uv", "run", "--python", v, "--with", "pip", "--no-project",
                "python", "-m", "pip", "wheel", str(sdist),
                "--no-deps", "--wheel-dir", str(wheelhouse),
            ])
        sdist.unlink()
    leftovers = [p.name for p in wheelhouse.iterdir() if not p.name.endswith(".whl")]
    if leftovers:
        raise SystemExit(
            f"non-wheel artifacts remain in the wheelhouse: {leftovers} -- "
            "the offline target could not install these without build tools"
        )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    os_name, arch = _platform_label()
    ap.add_argument(
        "--out",
        default=str(REPO / "build" / f"fv-offline-{os_name}-{arch}.zip"),
        help="output zip path (default: build/fv-offline-<os>-<arch>.zip)",
    )
    ap.add_argument(
        "--python-versions", nargs="+", default=list(DEFAULT_PY_VERSIONS),
        metavar="X.Y",
        help=f"CPython versions to cover (default: {' '.join(DEFAULT_PY_VERSIONS)})",
    )
    args = ap.parse_args()

    if shutil.which("uv") is None:
        raise SystemExit("uv not found on PATH -- https://docs.astral.sh/uv/")

    _ensure_spa()

    with tempfile.TemporaryDirectory(prefix="fv-offline-") as tmp:
        staging = Path(tmp) / "fv-offline"
        wheelhouse = staging / "wheelhouse"
        wheelhouse.mkdir(parents=True)

        version = _build_project_wheel(wheelhouse)
        _download_deps(wheelhouse, tuple(args.python_versions))

        shutil.copy2(HERE / "install.py", staging / "install.py")
        shutil.copy2(HERE / "README-OFFLINE.md", staging / "README-OFFLINE.md")
        (staging / "bundle-info.json").write_text(
            json.dumps(
                {
                    "name": "fermiviewer",
                    "version": version,
                    "os": os_name,
                    "arch": arch,
                    "python_versions": list(args.python_versions),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        out = Path(args.out).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        n = sum(1 for _ in wheelhouse.glob("*.whl"))
        print(f"zipping {n} wheels -> {out}")
        archive = shutil.make_archive(
            str(out.with_suffix("")), "zip", root_dir=tmp, base_dir="fv-offline"
        )
        size_mb = Path(archive).stat().st_size / 1e6
        print(f"done: {archive} ({size_mb:.0f} MB, fermiviewer {version}, "
              f"{os_name}-{arch}, py {' '.join(args.python_versions)})")


if __name__ == "__main__":
    main()
