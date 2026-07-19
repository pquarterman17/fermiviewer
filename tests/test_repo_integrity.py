"""Structural guards — the fermi-viewer ratchet idea, enforced forward.

Four invariants, checked forward so they never need retrofitting:

1. LICENSE GUARD — no GPL package in runtime dependencies. This project
   is Apache-2.0; rosettasciio/hyperspy live only in the 'oracle' dev
   group.
2. GOD-MODULE GUARD — no source module over MAX_MODULE_LINES. The MATLAB
   FermiViewer.m hit 14k lines before its painful decomposition; this
   ceiling makes that impossible by construction. Raise it ONLY with a
   written justification in the commit message.
3. LAYERING GUARD — io/ and calc/ never import fastapi/pydantic/routes.
   Pure-library isolation is what keeps their tests server-free.
4. FRONTEND MODULE RATCHET — new production TypeScript modules stay below
   500 lines; legacy giants may shrink but cannot grow before being split.
5. STYLESHEET RATCHET — split theme modules stay at or below 500 lines.
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
FRONTEND_SRC = ROOT / "frontend" / "src"

GPL_PACKAGES = {"rosettasciio", "rsciio", "hyperspy", "exspy", "holospy"}
MAX_MODULE_LINES = 500
FRONTEND_MAX_MODULE_LINES = 500
FRONTEND_MAX_STYLESHEET_LINES = 500
# Existing production modules above the default ceiling. These are debt, not
# precedent: each cap is its current size, so a module may shrink but not grow.
# Delete an entry as soon as that module is split below the default ceiling.
FRONTEND_LEGACY_CAPS = {
    "App.tsx": 630,
    "components/Inspector/MeasurePanel.tsx": 755,
    "components/Shell/MenuBar.tsx": 1583,
    "components/Stage/MeasureOverlay.tsx": 783,
    "components/Stage/Stage.tsx": 1234,
    "components/workshops/DiffractionWorkshop.tsx": 1090,
    "components/workshops/EdsSpectrumImage.tsx": 547,
    "components/workshops/EelsWorkshop.tsx": 806,
    "components/workshops/LayersWorkshop.tsx": 726,
    "components/workshops/StructureWorkshop.tsx": 1353,
    "store/viewer.ts": 1778,
}
PURE_LAYERS = ("io", "calc", "ops")
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


def test_frontend_module_size_ratchet() -> None:
    """Production TS modules have a 500-line default; legacy files are frozen."""
    offenders = []
    source_files = [*FRONTEND_SRC.rglob("*.ts"), *FRONTEND_SRC.rglob("*.tsx")]
    for path in source_files:
        if ".test." in path.name:
            continue
        relative = path.relative_to(FRONTEND_SRC).as_posix()
        limit = FRONTEND_LEGACY_CAPS.get(relative, FRONTEND_MAX_MODULE_LINES)
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if lines > limit:
            offenders.append(f"frontend/src/{relative}: {lines} lines (limit {limit})")
    assert not offenders, (
        "Frontend modules exceeded the size ratchet (split before adding more):\n  "
        + "\n  ".join(offenders)
    )


def test_frontend_stylesheet_size_ratchet() -> None:
    """Theme modules stay reviewable instead of regrowing a single CSS giant."""
    sheets = sorted(FRONTEND_SRC.rglob("*.css"))
    # A ratchet that finds nothing passes vacuously. If a move or rename ever
    # empties this sweep, fail loudly instead of silently guarding nothing.
    assert sheets, f"No stylesheets found under {FRONTEND_SRC.relative_to(ROOT)}"
    offenders = []
    for path in sheets:
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if lines > FRONTEND_MAX_STYLESHEET_LINES:
            offenders.append(f"{path.relative_to(ROOT)}: {lines} lines")
    assert not offenders, (
        f"Stylesheets over {FRONTEND_MAX_STYLESHEET_LINES} lines (split first):\n  "
        + "\n  ".join(offenders)
    )


# Shrink past this and the cap must be lowered to the new size — that is the
# ratchet locking the extraction in. Small slack so trivial edits don't churn.
FRONTEND_CAP_SLACK = 50


def test_frontend_legacy_caps_are_tight() -> None:
    """Caps only move DOWN: each must track its file (no re-growth headroom),
    and a file that fits the default ceiling must lose its cap entry."""
    stale, graduated, missing = [], [], []
    for relative, cap in FRONTEND_LEGACY_CAPS.items():
        path = FRONTEND_SRC / relative
        if not path.is_file():
            missing.append(relative)
            continue
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if lines <= FRONTEND_MAX_MODULE_LINES:
            graduated.append(f"{relative} ({lines} lines)")
        elif cap - lines > FRONTEND_CAP_SLACK:
            stale.append(f"{relative}: lower cap {cap} -> {lines}")
    assert not missing, f"caps for files that no longer exist: {missing}"
    assert not graduated, (
        f"these fit the {FRONTEND_MAX_MODULE_LINES}-line ceiling — delete "
        f"their FRONTEND_LEGACY_CAPS entries: {graduated}"
    )
    assert not stale, (
        "lock the extraction in by lowering the cap:\n  " + "\n  ".join(stale)
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
