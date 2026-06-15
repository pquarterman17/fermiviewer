"""Structural guards — the fermi-viewer ratchet idea, enforced forward.

Three invariants, checked from day one so they never need retrofitting:

1. LICENSE GUARD — no GPL package in runtime dependencies. This project
   is Apache-2.0; rosettasciio/hyperspy live only in the 'oracle' dev
   group.
2. GOD-MODULE GUARD — no source module over MAX_MODULE_LINES. The MATLAB
   FermiViewer.m hit 14k lines before its painful decomposition; this
   ceiling makes that impossible by construction. Raise it ONLY with a
   written justification in the commit message.
3. LAYERING GUARD — io/ and calc/ never import fastapi/pydantic/routes.
   Pure-library isolation is what keeps their tests server-free.
"""

from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # py<3.11 — backport (dev dep guarded by the same marker)
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "fermiviewer"

GPL_PACKAGES = {"rosettasciio", "rsciio", "hyperspy", "exspy", "holospy"}
MAX_MODULE_LINES = 500
PURE_LAYERS = ("io", "calc")
FORBIDDEN_IN_PURE = ("fastapi", "pydantic", "fermiviewer.routes", "starlette")


def test_no_gpl_in_runtime_deps() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    runtime = " ".join(pyproject["project"]["dependencies"]).lower()
    for pkg in GPL_PACKAGES:
        assert pkg not in runtime, (
            f"GPL package '{pkg}' in [project.dependencies] — Apache-2.0 "
            f"violation. Dev oracle deps belong in [dependency-groups].oracle."
        )
    # optional-dependencies (extras) ship to users too
    for extra, deps in pyproject["project"].get("optional-dependencies", {}).items():
        joined = " ".join(deps).lower()
        for pkg in GPL_PACKAGES:
            assert pkg not in joined, f"GPL package '{pkg}' in extra '{extra}'"


def test_no_god_modules() -> None:
    offenders = []
    for f in SRC.rglob("*.py"):
        n = len(f.read_text(encoding="utf-8").splitlines())
        if n > MAX_MODULE_LINES:
            offenders.append(f"{f.relative_to(ROOT)}: {n} lines")
    assert not offenders, (
        f"Modules over {MAX_MODULE_LINES} lines (split before merging):\n  "
        + "\n  ".join(offenders)
    )


def test_pure_layers_do_not_import_server_stack() -> None:
    pure_files = [SRC / "datastruct.py"]
    for layer in PURE_LAYERS:
        pure_files.extend((SRC / layer).rglob("*.py"))

    offenders = []
    for f in pure_files:
        for line in f.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not (stripped.startswith("import ") or stripped.startswith("from ")):
                continue
            if any(bad in stripped for bad in FORBIDDEN_IN_PURE):
                offenders.append(f"{f.relative_to(ROOT)}: {stripped}")
    assert not offenders, (
        "datastruct/io/calc are pure libraries — no server-stack imports:\n  "
        + "\n  ".join(offenders)
    )


def test_goldens_present_and_pinned() -> None:
    import json

    manifest = json.loads((ROOT / "tests" / "golden" / "manifest.json").read_text())
    assert manifest["sourceRepo"] == "fermi-viewer"
    assert manifest["sourceCommit"], "golden manifest missing source commit"
    assert manifest["skipped"] == [], (
        f"goldens were captured with skips: {manifest['skipped']} — re-run "
        "tools/matlab/freeze_reference_values.m cleanly before relying on them"
    )
