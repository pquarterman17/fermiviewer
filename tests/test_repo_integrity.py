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
# precedent: a cap only ever moves DOWN, so a module may shrink but not grow.
# Delete an entry as soon as that module is split below the default ceiling.
#
# A cap sits at roughly the module's size plus ~50 lines of slack, NOT at its
# exact size. Pinning tight looks stricter but is self-defeating: an
# extraction done specifically to make room for a booked feature then leaves
# zero room, so the very next line fails the ratchet and the gain cannot be
# spent. The slack is the working margin; the distance from the previous cap
# is what got banked.
FRONTEND_LEGACY_CAPS = {
    "components/Stage/Stage.tsx": 617,
    # store/viewer.ts graduated 2026-08-09 (W4 #22): 575 -> 448 lines, once
    # the close teardown moved to viewerCloseImage.ts and the appearance
    # preferences to viewerChromeActions.ts. It is a plain 500-line module now.
    # DiffractionWorkshop.tsx graduated 2026-08-10 (MAIN_PLAN item 1): 548 ->
    # 445 lines, once the Simulate-tab state/logic (phase list, CIF import/
    # delete, kinematic simulate) moved to useDiffractionSimulation.ts and the
    # elliptical-distortion calibration flow moved to
    # useDiffractionCalibration.ts, both under diffraction/.
    # MeasureOverlay.tsx graduated 2026-08-18 (LASSO_EDITING_PLAN item D):
    # 533 -> 472 lines, once the per-vertex handle rendering + drag/insert
    # mechanics (onHandleDown/Move/Up, whole-body translate, alt+edge-drag
    # vertex insertion) moved to MeasureVertexLayer.tsx. It is a plain
    # 500-line module now. Last legacy pin.
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


def test_node_version_declarations_agree() -> None:
    """Node is declared in four places; they must never drift apart.

    .nvmrc (repo root) is the single source: workflows read it via
    ``node-version-file`` (a hardcoded ``node-version:`` in any workflow is
    exactly how CI ran Node 20 while jsdom 30 required 22 — the v0.1.23-era
    Dependabot failure), frontend/package.json's ``engines`` range must
    contain it, and its ``volta`` pin must share the same major.
    """
    import json
    import re

    nvmrc = (ROOT / ".nvmrc").read_text().strip()
    major = int(nvmrc.split(".")[0])

    for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        text = wf.read_text()
        assert not re.search(r"^\s*node-version:", text, re.M), (
            f"{wf.name} hardcodes node-version — use node-version-file: "
            ".nvmrc so the repo file stays the single source of truth"
        )

    pkg = json.loads((ROOT / "frontend" / "package.json").read_text())
    engines = pkg["engines"]["node"]
    bounds = re.fullmatch(r">=(\d+) <(\d+)", engines)
    assert bounds, f"unexpected engines format: {engines!r}"
    low, high = int(bounds.group(1)), int(bounds.group(2))
    assert low <= major < high, (
        f".nvmrc Node {major} is outside engines range {engines!r}"
    )
    volta_major = int(pkg["volta"]["node"].split(".")[0])
    assert volta_major == major, (
        f"volta pins Node {volta_major} but .nvmrc says {major}"
    )


def test_project_version_declarations_agree() -> None:
    """The release version is declared in eight files; they must never drift.

    A ``chore(release): vX.Y.Z`` commit is exactly an 8-file, 2-line-each
    diff (pyproject, the package ``__version__``, frontend/package.json,
    tauri.conf.json, Cargo.toml, Cargo.lock, uv.lock, CHANGELOG). Lockfiles
    record the version too and a stale one fails ``--locked`` builds; a
    missing ``## [X.Y.Z]`` CHANGELOG section makes the GitHub Release fall
    back to an auto-generated commit list instead of the curated notes.
    Comparing every declaration to pyproject makes a partial bump fail
    here rather than in the release pipeline.
    """
    import json
    import re

    import fermiviewer

    expected = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"][
        "version"
    ]
    assert re.fullmatch(r"\d+\.\d+\.\d+", expected), expected

    tauri_dir = ROOT / "src-tauri"
    cargo_lock = tomllib.loads((tauri_dir / "Cargo.lock").read_text())
    uv_lock = tomllib.loads((ROOT / "uv.lock").read_text())

    def locked(lock: dict, name: str) -> str:
        pkgs = [p for p in lock["package"] if p["name"] == name]
        assert len(pkgs) == 1, f"{name!r} appears {len(pkgs)}× in lockfile"
        return str(pkgs[0]["version"])

    changelog = (ROOT / "CHANGELOG.md").read_text()
    top = re.search(r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.M)
    assert top, "CHANGELOG.md has no '## [X.Y.Z]' section"

    declared = {
        "src/fermiviewer/__init__.py": fermiviewer.__version__,
        "frontend/package.json": json.loads(
            (ROOT / "frontend" / "package.json").read_text()
        )["version"],
        "src-tauri/tauri.conf.json": json.loads(
            (tauri_dir / "tauri.conf.json").read_text()
        )["version"],
        "src-tauri/Cargo.toml": tomllib.loads(
            (tauri_dir / "Cargo.toml").read_text()
        )["package"]["version"],
        "src-tauri/Cargo.lock": locked(cargo_lock, "fermiviewer-shell"),
        "uv.lock": locked(uv_lock, "fermiviewer"),
        "CHANGELOG.md (topmost versioned section)": top.group(1),
    }
    drift = {k: v for k, v in declared.items() if v != expected}
    assert not drift, (
        f"pyproject.toml says {expected} but these disagree: {drift} — a "
        "release bump touches all eight files in ONE commit"
    )
