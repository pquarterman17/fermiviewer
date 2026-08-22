#!/usr/bin/env python3
"""Generate ``docs/operation-coverage.md`` — the GUI/headless parity audit
(roadmap item 3A, `plans/MICROSCOPY_FEATURE_ROADMAP.md`).

Regenerate after adding a route, registering an op, or reclassifying:

    uv run python tools/gen_coverage_table.py

``tests/test_coverage_table.py`` rebuilds this in memory on every test run
and fails if the committed file doesn't match byte-for-byte — never edit
the generated file by hand.

Two sources of truth are JOINED, so neither can silently drift:

* **Introspection** — the live FastAPI route table (`create_app()`) and
  the ops registry (`ops.list_ops()`). A curated row naming a route or op
  that no longer exists fails the build; a NEW route under an analysis
  prefix (`/api/analyze/`, `/api/eels/`, ...) that nobody classified
  fails the build too, so the audit cannot quietly go stale.
* **Curated classification** — which GUI surface calls each analysis
  endpoint, which registered op (if any) backs it, its ADR 0004 result
  kinds, and its roadmap wave. These are judgements, not introspectable
  facts, and they live here as data.

Output is deterministic: curated rows render in declaration order,
derived listings sort, and no timestamps or version strings are embedded
(a version string made every release bump stale `docs/api-reference.md`
once — same rule here).

App-layer tool (like ``tools/gen_api_reference.py``): imports
``fermiviewer`` and stdlib only.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import fermiviewer.ops as fvops  # noqa: E402

OUT_PATH = ROOT / "docs" / "operation-coverage.md"

#: Route prefixes where every endpoint MUST be classified below (analysis,
#: reference, or the explicit infrastructure list). A new endpoint under
#: one of these that nobody classified is exactly the drift this audit
#: exists to catch, so it fails the build instead of hiding.
GUARDED_PREFIXES = (
    "/api/analyze/",
    "/api/atoms/",
    "/api/diffraction/",
    "/api/eds/",
    "/api/eels/",
    "/api/fourd",
    "/api/grains/",
    "/api/measure/",
    "/api/regions/",
)

#: The 14 /api/filter kinds that dispatch to registered filter/geometry
#: ops. The route additionally accepts `crop` and arbitrary-angle
#: `rotate`, which have NO op (mirrored by the frontend's
#: `lib/macroOpMap.ts` FILTER_OP_NAMES — the generated table is the
#: reference that file should follow).
FILTER_OPS = (
    "gaussian",
    "median",
    "unsharp",
    "butterworth",
    "clahe",
    "bin",
    "plane_level",
    "morph",
    "multiotsu",
    "rotate90",
    "rotate180",
    "rotate270",
    "fliph",
    "flipv",
)


@dataclass(frozen=True)
class Row:
    """One analysis endpoint's coverage judgement."""

    method: str
    path: str
    gui: str  # calling GUI surface; "— (no GUI caller)" marks an orphan
    ops: tuple[str, ...] = ()  # registered op name(s) backing it, if any
    kinds: str = ""  # ADR 0004 output kinds of today's payload
    wave: str = ""  # "shipped" | "A" | "B" | "C" | "parked" | "" (unassigned)
    note: str = ""


@dataclass(frozen=True)
class Domain:
    title: str
    rows: tuple[Row, ...] = field(default_factory=tuple)


# ── curated classification ───────────────────────────────────────────

DOMAINS: tuple[Domain, ...] = (
    Domain(
        "Imaging & texture",
        (
            Row(
                "POST",
                "/api/filter",
                "Image menu, Stage tools",
                FILTER_OPS,
                "map (derived image)",
                "shipped",
                "`crop` and arbitrary-angle `rotate` kinds have no op",
            ),
            Row("POST", "/api/strip-databar", "Image menu", (), "map (derived image)"),
            Row(
                "POST",
                "/api/image/{img_id}/fft",
                "Image menu; Lattice/GPA/FFT-mask modes",
                (),
                "map",
                "B",
            ),
            Row("POST", "/api/analyze/fft-mask", "FFT Mask workshop", (), "map", "B"),
            Row("POST", "/api/analyze/vdf", "Image menu", (), "map", "B"),
            Row(
                "POST",
                "/api/analyze/gpa",
                "Structure workshop, Template/GPA mode",
                (),
                "map ×4 + scalar ×4",
                "B",
            ),
            Row(
                "POST",
                "/api/analyze/radial",
                "Image menu",
                ("radial_profile",),
                "curve ×2",
                "shipped",
                "azimuthal sector mode has no op",
            ),
            Row(
                "POST",
                "/api/analyze/roughness",
                "Roughness workshop",
                ("roughness",),
                "scalar set + curve (bearing)",
                "shipped",
                "route adds bearing curve + ROI",
            ),
            Row(
                "POST",
                "/api/analyze/noise",
                "Noise workshop",
                ("noise",),
                "scalar set + fit + curve",
                "shipped",
                "route adds block stats + ROI",
            ),
            Row("POST", "/api/analyze/interface-width", "Interface Width workshop", (), "fit", "A"),
            Row("POST", "/api/analyze/lattice", "Lattice mode", (), "scalar set", "B"),
            Row(
                "POST",
                "/api/analyze/ctf",
                "Structure workshop, CTF mode",
                (),
                "fit + curve ×2 + scalar",
                "B",
            ),
            Row("POST", "/api/analyze/montage", "Image menu", (), "figure", "C"),
            Row("POST", "/api/analyze/montage-compare", "— (no GUI caller)", (), "figure", "C"),
        ),
    ),
    Domain(
        "Structure & particles",
        (
            Row(
                "POST",
                "/api/analyze/particles",
                "Structure workshop, Particles mode",
                (),
                "table + map (label map)",
                "A",
            ),
            Row("POST", "/api/analyze/efd-similarity", "Particles mode", (), "table", "A"),
            Row(
                "POST",
                "/api/analyze/fit-shape",
                "Inspector, Regions card",
                (),
                "fit ×2 + overlay",
                "A",
            ),
            Row("POST", "/api/regions/propose", "Inspector, Regions card", (), "overlay", "A"),
            Row(
                "POST",
                "/api/analyze/atoms",
                "Atom Column panel",
                (),
                "table + overlay + scalar",
                "B",
            ),
            Row("POST", "/api/atoms/strain", "Atom Column panel", (), "table + scalar", "B"),
            Row(
                "POST",
                "/api/analyze/template-match",
                "Template/GPA mode",
                (),
                "table + overlay",
                "B",
            ),
            Row(
                "POST",
                "/api/analyze/defects",
                "Defect workshop",
                (),
                "scalar + overlay + map ×2",
                "B",
            ),
            Row(
                "POST",
                "/api/analyze/distribution",
                "Population histogram panel",
                ("distribution_fit",),
                "scalar set + curve + fit ×3",
                "shipped",
            ),
        ),
    ),
    Domain(
        "Grains & layers",
        (
            Row(
                "POST",
                "/api/analyze/grains",
                "Structure workshop, Grains mode",
                (),
                "table + map + overlay + scalar (job)",
                "A",
            ),
            Row(
                "POST",
                "/api/grains/edit",
                "Stage grain merge/split",
                (),
                "table + map + overlay + scalar",
                "A",
            ),
            Row(
                "POST",
                "/api/grains/train-segment",
                "Grains mode, Trained panel",
                (),
                "table + map + overlay + scalar",
                "A",
            ),
            Row(
                "POST",
                "/api/grains/train-preview",
                "Grains mode, Trained panel",
                (),
                "map ×2 + scalar ×2",
                "A",
            ),
            Row(
                "POST",
                "/api/analyze/layers",
                "Layers workshop",
                (),
                "curve + table + fit (per interface)",
                "A",
            ),
            Row(
                "POST",
                "/api/analyze/layers/edit",
                "Layers workshop",
                (),
                "curve + table + fit",
                "A",
            ),
            Row(
                "POST",
                "/api/analyze/layers/grains",
                "Cross-section per-layer view",
                (),
                "table",
                "A",
            ),
            Row(
                "POST",
                "/api/analyze/layers/multi",
                "Layers multi-compare",
                (),
                "table + map refs",
                "A",
            ),
        ),
    ),
    Domain(
        "Stacks & mosaics",
        (
            Row("POST", "/api/analyze/align-stack", "Image menu", (), "map ×N + table", "C"),
            Row("POST", "/api/analyze/mip", "Image menu", (), "map", "C"),
            Row("POST", "/api/analyze/stitch", "CTF/Stitch mode", (), "map + table", "C"),
            Row("POST", "/api/analyze/image-math", "Image menu", (), "map", "C"),
            Row(
                "POST",
                "/api/analyze/back-project",
                "Analysis menu",
                (),
                "map",
                "",
                "tomography — parked with roadmap item 9",
            ),
        ),
    ),
    Domain(
        "EELS",
        (
            Row("POST", "/api/eels/background", "EELS workshop", (), "curve ×3"),
            Row("POST", "/api/eels/map", "EELS workshop", ("eels_map",), "map", "shipped"),
            Row(
                "POST",
                "/api/eels/quantify",
                "EELS workshop",
                ("eels_quantify",),
                "table",
                "shipped",
            ),
            Row("POST", "/api/eels/fit", "EELS workshop", ("eels_fit",), "fit", "shipped"),
            Row("POST", "/api/eels/fit-map", "EELS workshop", (), "map ×N + table"),
            Row("POST", "/api/eels/quantify-map", "EELS quant-map job", (), "map ×N"),
            Row("POST", "/api/eels/thickness", "EELS Advanced", (), "map + scalar ×2"),
            Row("POST", "/api/eels/kk", "EELS Advanced", (), "curve ×5 + scalar ×2"),
            Row("POST", "/api/eels/fourier-log", "EELS Advanced", (), "curve ×2 + scalar"),
            Row("POST", "/api/eels/svd", "EELS Advanced", (), "curve ×k + map ×k"),
            Row("POST", "/api/eels/align-zlp", "EELS Advanced", (), "map + scalar ×2"),
            Row("POST", "/api/eels/subpixel-align", "EELS Advanced", (), "map + scalar ×2"),
            Row("POST", "/api/eels/richardson-lucy", "EELS Advanced", (), "curve ×2 + scalar"),
            Row("POST", "/api/eels/maps", "Elemental workspace", (), "map ×N"),
            Row("POST", "/api/eels/auto-assign", "Elemental workspace", (), "table"),
            Row("POST", "/api/analyze/elnes", "EELS workshop", (), "curve"),
        ),
    ),
    Domain(
        "EDS",
        (
            Row(
                "POST",
                "/api/eds/quantify",
                "EDS Quantify panel",
                ("eds_quantify",),
                "table + map ×N",
                "shipped",
            ),
            Row(
                "POST",
                "/api/eds/peakfit",
                "EDS Model Fit",
                ("eds_peakfit",),
                "fit + table",
                "shipped",
                "op and route use different entry points into calc/eds_peakfit",
            ),
            Row("POST", "/api/eds/zeta", "EDS Model Fit", (), "fit + table + scalar"),
            Row("POST", "/api/eds/continuum", "EDS Model Fit", (), "fit + curve"),
            Row(
                "POST",
                "/api/eds/artifacts",
                "— (wrapper only, no GUI caller)",
                (),
                "curve ×2 + table",
            ),
            Row("POST", "/api/eds/recalibrate", "EDS Model Fit", (), "fit (calibration)"),
            Row(
                "POST",
                "/api/eds/element-map",
                "Elemental workspace",
                ("eds_element_map",),
                "map + scalar",
                "shipped",
            ),
            Row(
                "POST",
                "/api/eds/element-maps",
                "Elemental workspace",
                ("eds_element_maps",),
                "map ×N",
                "shipped",
            ),
            Row("POST", "/api/eds/auto-assign", "EDS Quantify panel, Maps tab", (), "table"),
            Row(
                "POST",
                "/api/analyze/composition-profile",
                "EDS Quantify panel",
                ("composition_profile",),
                "curve ×N (σ-bearing)",
                "shipped",
                "op quantifies the cube itself; route samples pre-registered maps",
            ),
        ),
    ),
    Domain(
        "Diffraction",
        (
            Row(
                "POST",
                "/api/diffraction/detect",
                "Diffraction workshop",
                (),
                "table + overlay",
                "C",
            ),
            Row("POST", "/api/diffraction/index", "Diffraction workshop", (), "table", "C"),
            Row(
                "POST",
                "/api/diffraction/calibrate",
                "Diffraction calibration",
                (),
                "fit + scalar ×2",
                "C",
            ),
            Row(
                "POST",
                "/api/analyze/simulate",
                "Diffraction simulation",
                (),
                "table + map + scalar",
                "C",
            ),
        ),
    ),
    Domain(
        "Measurement",
        (
            Row("POST", "/api/measure/profile", "Measure panel, Stage", (), "curve + scalar"),
            Row("POST", "/api/measure/roi", "Measure panel", (), "scalar set"),
            Row("POST", "/api/measure/box-profile", "Measure panel", (), "curve ×2"),
            Row(
                "POST",
                "/api/measure/distance-tilted",
                "— (wrapper only, no GUI caller)",
                (),
                "scalar set",
            ),
            Row("GET", "/api/image/{img_id}/spectrum", "Spectrum panel", (), "curve"),
            Row("GET", "/api/image/{img_id}/histogram", "Histogram panel", (), "curve"),
            Row("POST", "/api/calibration/detect-bar", "Calibration dialog", (), "scalar set"),
        ),
    ),
    Domain(
        "4D-STEM",
        (
            Row("GET", "/api/fourd/{fourd_id}/nav", "4D workshop", (), "map", "parked"),
            Row("GET", "/api/fourd/{fourd_id}/pattern", "4D workshop", (), "map", "parked"),
            Row("GET", "/api/fourd/{fourd_id}/mean-pattern", "4D workshop", (), "map", "parked"),
            Row(
                "POST",
                "/api/fourd/{fourd_id}/virtual-detector",
                "4D aperture controls",
                (),
                "map",
                "parked",
            ),
            Row("POST", "/api/fourd/{fourd_id}/com", "4D COM output", (), "map ×2", "parked"),
            Row("POST", "/api/fourd/{fourd_id}/dpc", "4D COM output", (), "map ×2", "parked"),
            Row("POST", "/api/fourd/{fourd_id}/idpc", "4D COM output", (), "map", "parked"),
        ),
    ),
)

#: Physics-table lookups: no data reduction, so no op is owed.
REFERENCE: tuple[tuple[str, str], ...] = (
    ("GET", "/api/diffraction/phases"),
    ("GET", "/api/eds/line-energy/{symbol}"),
    ("GET", "/api/eds/lines"),
)

#: Endpoints under a guarded prefix that are deliberately NOT analysis:
#: dataset/phase-store management, not computation.
GUARDED_INFRASTRUCTURE: tuple[tuple[str, str], ...] = (
    ("POST", "/api/diffraction/phases/import"),
    ("DELETE", "/api/diffraction/phases/{name}"),
    ("GET", "/api/fourd"),
    ("DELETE", "/api/fourd/{fourd_id}"),
    ("GET", "/api/fourd/{fourd_id}/meta"),
    ("POST", "/api/fourd/{fourd_id}/reshape"),
)

WAVE_LABEL = {
    "shipped": "shipped",
    "A": "wave A",
    "B": "wave B",
    "C": "wave C",
    "parked": "parked (item 8/9)",
    "": "—",
}


# ── introspection ────────────────────────────────────────────────────


def app_routes() -> set[tuple[str, str]]:
    """(method, path) for every HTTP endpoint the app serves."""
    from fastapi.routing import APIRoute

    from fermiviewer.server import create_app

    found: set[tuple[str, str]] = set()

    def visit(routes: list, prefix: str) -> None:
        for route in routes:
            if isinstance(route, APIRoute):
                for method in (route.methods or set()) - {"HEAD", "OPTIONS"}:
                    found.add((method, prefix + route.path))
            elif hasattr(route, "original_router"):
                # FastAPI's lazily-included router wrapper: recurse with
                # the include-time prefix applied.
                inner_prefix = getattr(route.include_context, "prefix", "") or ""
                visit(route.original_router.routes, prefix + inner_prefix)

    visit(create_app().routes, "")
    return found


def curated_analysis() -> list[Row]:
    return [row for domain in DOMAINS for row in domain.rows]


def cross_check() -> None:
    """Fail loudly on any drift between the app, the registry, and the
    curated classification — this is what makes the audit trustworthy."""
    live = app_routes()
    rows = curated_analysis()
    curated = {(row.method, row.path) for row in rows}
    stated = curated | set(REFERENCE) | set(GUARDED_INFRASTRUCTURE)

    missing = sorted(stated - live)
    if missing:
        raise SystemExit(f"classified routes not served by the app: {missing}")

    unclassified = sorted(
        (method, path) for method, path in live - stated if path.startswith(GUARDED_PREFIXES)
    )
    if unclassified:
        raise SystemExit(
            "new analysis-prefix routes need a classification in "
            f"tools/gen_coverage_table.py: {unclassified}"
        )

    registered = {spec.name for spec in fvops.list_ops()}
    for row in rows:
        unknown = sorted(set(row.ops) - registered)
        if unknown:
            raise SystemExit(f"{row.path} names unregistered op(s): {unknown}")


# ── rendering ────────────────────────────────────────────────────────


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def _row_line(row: Row) -> str:
    ops = ", ".join(f"`{name}`" for name in row.ops) if row.ops else "—"
    gui = row.gui if not row.note else f"{row.gui}. *{row.note}*"
    return (
        f"| `{row.method} {row.path}` | {_cell(gui)} | {ops} "
        f"| {_cell(row.kinds)} | {WAVE_LABEL[row.wave]} |"
    )


def _summary(live: set[tuple[str, str]]) -> list[str]:
    rows = curated_analysis()
    opped = sum(1 for row in rows if row.ops)
    waves = {key: sum(1 for r in rows if r.wave == key) for key in ("A", "B", "C")}
    n_ops = len(fvops.list_ops())
    return [
        f"- **{len(live)}** HTTP endpoints; **{len(rows)}** perform analysis, "
        f"{len(REFERENCE)} are physics-table lookups, the rest are "
        "session/project/render/export infrastructure.",
        f"- **{opped} of {len(rows)}** analysis endpoints are backed by a "
        f"registered op (the `/api/filter` row alone carries {len(FILTER_OPS)}); "
        f"the registry holds **{n_ops}** ops in total.",
        "- Registered-op reach IS headless reach: batch recipes, folder "
        "watch, `fv --script`, and the Python API all resolve steps through "
        "the same registry and cannot call anything else.",
        f"- Remaining item-3 work: wave A ({waves['A']}), wave B "
        f"({waves['B']}), wave C ({waves['C']}) endpoints; spectroscopy, "
        "measurement and utility endpoints marked — are not yet assigned "
        "to a wave.",
    ]


def _analysis_sections() -> list[str]:
    lines: list[str] = []
    header = (
        "| Route | GUI action | Registered op (headless reach) | Result kinds (ADR 0004) | Wave |"
    )
    rule = "|---|---|---|---|---|"
    for domain in DOMAINS:
        lines += [f"### {domain.title}", "", header, rule]
        lines += [_row_line(row) for row in domain.rows]
        lines.append("")
    return lines


def _ops_without_routes() -> list[str]:
    referenced = {name for row in curated_analysis() for name in row.ops}
    stranded = [spec for spec in fvops.list_ops() if spec.name not in referenced]
    lines = [
        "## Registered ops with no route",
        "",
        "Reachable from batch/Python but absent from the GUI's own wiring "
        "(`image_stats` reaches the GUI only via `/api/export/table`).",
        "",
    ]
    lines += [f"- `{spec.name}` — {_cell(spec.summary)}" for spec in stranded]
    lines.append("")
    return lines


def _compact_listing(title: str, blurb: str, pairs: list[tuple[str, str]]) -> list[str]:
    lines = [f"## {title}", "", blurb, ""]
    lines += [f"- `{method} {path}`" for method, path in pairs]
    lines.append("")
    return lines


def build_markdown() -> str:
    """The whole document as a string; no filesystem I/O (the drift-guard
    test compares this against the committed file without touching it)."""
    cross_check()
    live = app_routes()
    stated_analysis = {(r.method, r.path) for r in curated_analysis()}
    infra = sorted(
        live - stated_analysis - set(REFERENCE),
        key=lambda pair: (pair[1], pair[0]),
    )

    lines: list[str] = [
        "<!-- AUTO-GENERATED by tools/gen_coverage_table.py — do not edit by hand.",
        "     Regenerate: uv run python tools/gen_coverage_table.py -->",
        "",
        "# GUI / headless operation coverage",
        "",
        "The parity audit for roadmap item 3 "
        "(`plans/MICROSCOPY_FEATURE_ROADMAP.md`): every analysis endpoint, "
        "the GUI surface that calls it, the registered op that makes it "
        "reachable headlessly (batch recipes, folder watch, `fv --script`, "
        "and `fermiviewer.api` all resolve through the ops registry — one "
        "column covers all four), the ADR 0004 output kinds of today's "
        "response, and the item-3 wave that will close each gap. Macro "
        "record/replay converges on the same registry for exactly the "
        "op-backed wire calls; everything else it records is replay-only "
        "(`frontend/src/lib/macroOpMap.ts` mirrors this table).",
        "",
        "Route and op inventories are read live from the app and registry "
        "at generation time; classifications are curated in "
        "`tools/gen_coverage_table.py`. A new analysis-prefix route without "
        "a classification fails the build, and "
        "`tests/test_coverage_table.py` fails if this file drifts from a "
        "regeneration.",
        "",
        "## Summary",
        "",
        *_summary(live),
        "",
        "## Analysis endpoints",
        "",
        *_analysis_sections(),
        *_ops_without_routes(),
        *_compact_listing(
            "Reference lookups",
            "Physics tables, no data reduction — no op is owed.",
            list(REFERENCE),
        ),
        *_compact_listing(
            "Infrastructure endpoints",
            "Session, project, render, export, jobs, calibration-store and "
            "dataset plumbing — outside the parity audit's scope.",
            infra,
        ),
    ]
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    OUT_PATH.write_text(build_markdown(), encoding="utf-8")
    print(OUT_PATH.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
