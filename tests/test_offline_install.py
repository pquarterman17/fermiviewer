"""Offline / air-gapped install path (hatch_build.py + tools/offline/).

The wheel is the deliverable for air-gapped machines, so the SPA must
ride inside it — and the two tools/offline scripts must at least parse
and answer --help on every supported interpreter (the CI matrix runs
this file on the 3.10 floor, which catches accidental new-Python
syntax in scripts that ship to arbitrary target machines).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OFFLINE = ROOT / "tools" / "offline"


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv on PATH")
@pytest.mark.skipif(
    not (ROOT / "frontend" / "dist" / "index.html").is_file(),
    reason="frontend/dist not built",
)
def test_wheel_bakes_spa(tmp_path: Path) -> None:
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=ROOT, check=True, capture_output=True,
    )
    (whl,) = tmp_path.glob("fermiviewer-*.whl")
    names = zipfile.ZipFile(whl).namelist()
    assert "fermiviewer/_spa/index.html" in names, "SPA missing from the wheel"
    assert any(n.startswith("fermiviewer/_spa/assets/") for n in names), (
        "SPA JS/CSS assets missing from the wheel"
    )
    # force_include must not displace the existing artifact includes
    assert any("assets/fonts" in n and n.endswith(".ttf") for n in names), (
        "vendored font dropped from the wheel"
    )


@pytest.mark.parametrize("script", ["make_bundle.py", "install.py"])
def test_offline_scripts_answer_help(script: str) -> None:
    r = subprocess.run(
        [sys.executable, str(OFFLINE / script), "--help"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "usage" in r.stdout.lower()


def test_bundle_default_python_versions_match_floor() -> None:
    """The bundler's coverage must start at pyproject's requires-python
    floor — a bundle that silently drops the floor strands target
    machines that CLAUDE.md/README promise are supported."""
    sys.path.insert(0, str(OFFLINE))
    try:
        import make_bundle
    finally:
        sys.path.pop(0)
    assert make_bundle.DEFAULT_PY_VERSIONS[0] == "3.10"
    assert list(make_bundle.DEFAULT_PY_VERSIONS) == sorted(
        make_bundle.DEFAULT_PY_VERSIONS, key=lambda v: tuple(map(int, v.split(".")))
    )
