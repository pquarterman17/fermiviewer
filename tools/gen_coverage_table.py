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
  that no longer exists fails the build; so does ANY live route that no
  classification covers — every endpoint is explicitly analysis,
  reference, or infrastructure, and infrastructure is an allowlist, not
  the unchecked remainder. A new route cannot silently hide as plumbing.
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
    #: Every row MUST carry an assignment (cross_check enforces it): a
    #: shipped op, one of waves A-D, or parked behind an item-8/9 gate.
    #: "Unassigned" is not a state — that is how endpoints disappear from
    #: a "universal" parity plan.
    wave: str = ""  # "shipped" | "A" | "B" | "C" | "D" | "parked"
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
            Row(
                "POST",
                "/api/strip-databar",
                "Image menu",
                ("strip_databar",),
                "map (derived image)",
                "shipped",
                "the tree's first ops->io import (both pure layers); static "
                "source name in the pure layer",
            ),
            Row(
                "POST",
                "/api/image/{img_id}/fft",
                "Image menu; Lattice/GPA/FFT-mask modes",
                ("fft",),
                "map",
                "shipped",
                "op flattens the optional local-FFT rect to NaN-sentinel floats; "
                "the derived image drops calibration (FFT space)",
            ),
            Row(
                "POST",
                "/api/analyze/fft-mask",
                "FFT Mask workshop",
                ("fft_mask",),
                "map",
                "shipped",
                "the gap-2 exemplar: `masks` rides the contract's row-list "
                "param type (ADR 0005 §9) as real (row, col, radius) triples",
            ),
            Row(
                "POST",
                "/api/analyze/vdf",
                "Image menu",
                ("vdf",),
                "map",
                "shipped",
                "op flattens the aperture centre to two required floats",
            ),
            Row(
                "POST",
                "/api/analyze/gpa",
                "Structure workshop, Template/GPA mode",
                ("gpa",),
                "map ×4 + scalar ×4",
                "shipped",
                "the four strain maps inline as `map` envelopes in the op; the "
                "route registers them as session images (grains precedent, "
                "ADR 0005 wave-B addendum)",
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
            Row(
                "POST",
                "/api/analyze/interface-width",
                "Interface Width workshop",
                ("interface_width",),
                "fit",
                "shipped",
                "no image subject — op ignores `ds`, profile travels as x/y CSV "
                "(`distribution_fit` precedent, blessed in ADR 0005's wave-A addendum)",
            ),
            Row(
                "POST",
                "/api/analyze/lattice",
                "Lattice mode",
                ("lattice",),
                "scalar set",
                "shipped",
                "op flattens the two FFT spot picks to four required floats; "
                "unset pixel_size (NaN) falls back to the image calibration",
            ),
            Row(
                "POST",
                "/api/analyze/ctf",
                "Structure workshop, CTF mode",
                ("ctf",),
                "fit + curve ×2 + scalar",
                "shipped",
                "the route's exclusive pixel_size_a > 0 bound is enforced in "
                "the op fn (OpParam has no exclusive minimum — ADR 0005 "
                "wave-B addendum)",
            ),
            Row(
                "POST",
                "/api/analyze/montage",
                "Image menu",
                ("montage",),
                "map (derived image)",
                "shipped",
                "subject = first frame, rest variadic (ADR 0005 §8). "
                "Per-input labels come from each dataset's metadata "
                "`source` — the pure layer composes no session names, the "
                "divergence the wave-C addendum predicted. `overlap`'s "
                "lt=1.0 now has a real schema spelling (exclusive_maximum)",
            ),
            Row(
                "POST",
                "/api/analyze/montage-compare",
                "— (no GUI caller)",
                ("montage_compare",),
                "map (derived image)",
                "shipped",
                "the joint gap-1 + gap-2 case: tiles are a variadic input "
                "(§8) and their per-tile metadata a RecordSpec (§9). "
                "`param_value` MUST be ANY_SCALAR — the panel order "
                "distinguishes real numerics from numeric-looking strings "
                "and excludes bool, so any narrower ptype would reorder the "
                "panels differently from the route",
            ),
        ),
    ),
    Domain(
        "Structure & particles",
        (
            Row(
                "POST",
                "/api/analyze/particles",
                "Structure workshop, Particles mode",
                ("particles",),
                "table + map (label map)",
                "shipped",
                "op flattens `class_thresholds` to four NaN-sentinel floats "
                "resolved against calc defaults",
            ),
            Row(
                "POST",
                "/api/analyze/efd-similarity",
                "Particles mode",
                ("efd_similarity",),
                "table",
                "shipped",
                "op drops the route's dead inherited `class_thresholds` field",
            ),
            Row(
                "POST",
                "/api/analyze/fit-shape",
                "Inspector, Regions card",
                ("fit_shape",),
                "fit ×2 + overlay",
                "shipped",
                "`points` rides a RowSpec list param (ADR 0005 §9); the op "
                "takes the subject and ignores it, the wave-A no-subject "
                "precedent. Points are 1-based (row, col)",
            ),
            Row(
                "POST",
                "/api/regions/propose",
                "Inspector, Regions card",
                ("propose_region",),
                "overlay",
                "shipped",
                "op flattens seed/rect to NaN-sentinel floats "
                "(`composition_profile` x1/y1 precedent)",
            ),
            Row(
                "POST",
                "/api/analyze/atoms",
                "Atom Column panel",
                ("atoms",),
                "table + overlay + scalar",
                "shipped",
                "the detect/refine/lattice/sublattice/strain composition is "
                "lifted to calc/atom_report.py, shared with /atoms/strain",
            ),
            Row(
                "POST",
                "/api/atoms/strain",
                "Atom Column panel",
                ("atoms_strain",),
                "table + scalar",
                "shipped",
                "`positions` rides a RowSpec list param (ADR 0005 §9), "
                "1-based (x, y) — the OPPOSITE order to fit_shape's "
                "(row, col). Optional `origin` is a NaN-sentinel pair, the "
                "route's field being a flat [x0, y0]",
            ),
            Row(
                "POST",
                "/api/analyze/template-match",
                "Template/GPA mode",
                ("template_match",),
                "table + overlay",
                "shipped",
                "op flattens the template rect to four required ints — "
                "(row, col, height, width), deliberately NOT the corner-ROI "
                "string other ops use",
            ),
            Row(
                "POST",
                "/api/analyze/defects",
                "Defect workshop",
                ("defects",),
                "scalar + overlay + map ×2",
                "shipped",
                "the two diagnostic maps inline as `map` envelopes in the op; "
                "the route registers them as session images (grains "
                "precedent, ADR 0005 wave-B addendum)",
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
                ("grains",),
                "table + map + overlay + scalar (job)",
                "shipped",
                "op registers the synchronous computation; `run_async` job "
                "orchestration stays route-only (ADR 0005 §6)",
            ),
            Row(
                "POST",
                "/api/grains/edit",
                "Stage grain merge/split",
                ("grains_edit",),
                "table + map + overlay + scalar",
                "shipped",
                "subject = the label map, source image as a named input "
                "(§8) instead of a metadata + store lookup; clicks ride a "
                "RowSpec list, 0-based (x, y). Numerics lifted to "
                "calc/grain_edit.py, which also adds the labels/raster "
                "shape check the route never had",
            ),
            Row(
                "POST",
                "/api/grains/train-segment",
                "Grains mode, Trained panel",
                ("train_segment",),
                "table + map + overlay + scalar",
                "shipped",
                "scribble strokes are the RecordSpec case §9 opened — a "
                "record whose `points` field is itself a row list, the one "
                "level of nesting the contract allows",
            ),
            Row(
                "POST",
                "/api/grains/train-preview",
                "Grains mode, Trained panel",
                ("train_preview",),
                "map ×2 + scalar ×2",
                "shipped",
                "same RecordSpec strokes as train-segment (minus min_area); "
                "the two maps inline as `map` envelopes on the wave-B "
                "standing rule. The route's 0.6 confidence threshold is "
                "lifted to calc/grains_trained.confidence_summary",
            ),
            Row(
                "POST",
                "/api/analyze/layers",
                "Layers workshop",
                ("layers",),
                "curve + table + fit (per interface)",
                "shipped",
            ),
            Row(
                "POST",
                "/api/analyze/layers/edit",
                "Layers workshop",
                ("layers_edit",),
                "curve + table + fit",
                "shipped",
                "op flattens `positions` to a CSV float list (`distribution_fit` values precedent)",
            ),
            Row(
                "POST",
                "/api/analyze/layers/grains",
                "Cross-section per-layer view",
                ("layers_grains",),
                "table",
                "shipped",
                "subject = the label map, with the source image as a named "
                "input (ADR 0005 §8) instead of a metadata + store lookup. "
                "Layer bands ride a RecordSpec; `interface_traces` is the "
                "one ragged, null-accepting row list (§9)",
            ),
            Row(
                "POST",
                "/api/analyze/layers/multi",
                "Layers multi-compare",
                ("layers_multi",),
                "table + map refs",
                "shipped",
                "subject = the REFERENCE map (its detected axis and "
                "interface positions govern every other map), with the rest "
                "as a variadic input (ADR 0005 §8); the route's `reference` "
                "index param is dropped as a second way to say the same "
                "thing. Cross-map calibration checks lifted to "
                "calc/layers_multi.py",
            ),
        ),
    ),
    Domain(
        "Stacks & mosaics",
        (
            Row(
                "POST",
                "/api/analyze/align-stack",
                "Image menu",
                ("align_stack",),
                "map ×N + table",
                "shipped",
                "a gap-1 exemplar: subject = reference frame, `others` is a "
                "variadic input (ADR 0005 §8). The N-1 aligned rasters inline "
                "as `map` envelopes; the route registers session images",
            ),
            Row(
                "POST",
                "/api/analyze/mip",
                "Image menu",
                ("mip",),
                "map",
                "shipped",
                "a gap-1 exemplar: subject = first frame, `others` is a "
                "variadic input (ADR 0005 §8)",
            ),
            Row(
                "POST",
                "/api/analyze/stitch",
                "CTF/Stitch mode",
                ("stitch",),
                "map + table",
                "shipped",
                "subject = first tile, rest variadic (ADR 0005 §8). The "
                "equal-size precondition is reproduced in the op: "
                "`stitch_images` sizes its canvas from the first tile, so "
                "unequal tiles would silently crop",
            ),
            Row(
                "POST",
                "/api/analyze/image-math",
                "Image menu",
                ("image_math",),
                "map",
                "shipped",
                "the gap-1 exemplar: the subject is a_id and `other` is a "
                "named input the CALLER resolves (ADR 0005 §8), so the op "
                "still never reads the session store",
            ),
            Row(
                "POST",
                "/api/analyze/back-project",
                "Analysis menu",
                (),
                "map",
                "parked",
                "tomography — parked with roadmap item 9",
            ),
        ),
    ),
    Domain(
        "EELS",
        (
            Row(
                "POST",
                "/api/eels/background",
                "EELS workshop",
                ("eels_background",),
                "curve ×3",
                "shipped",
            ),
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
            Row(
                "POST",
                "/api/eels/fit-map",
                "EELS workshop",
                ("eels_fit_map",),
                "map ×N + table",
                "shipped",
                "edges via the shipped six-CSV schema; per-element maps inline",
            ),
            Row(
                "POST",
                "/api/eels/quantify-map",
                "EELS quant-map job",
                ("eels_quantify_map",),
                "map ×N",
                "shipped",
                "op registers the synchronous computation; run_async job "
                "orchestration stays route-only (ADR 0005 §6)",
            ),
            Row(
                "POST",
                "/api/eels/thickness",
                "EELS Advanced",
                ("eels_thickness",),
                "map + scalar ×2",
                "shipped",
                "op inlines the RAW t/lambda map (NaN -> null) where the route "
                "registers nan_to_num(t) — zero-filling would bias headless means "
                "(ADR 0005 wave-D addendum)",
            ),
            Row(
                "POST",
                "/api/eels/kk",
                "EELS Advanced",
                ("eels_kk",),
                "curve ×5 + scalar ×2",
                "shipped",
            ),
            Row(
                "POST",
                "/api/eels/fourier-log",
                "EELS Advanced",
                ("eels_fourier_log",),
                "curve ×2 + scalar",
                "shipped",
            ),
            Row(
                "POST",
                "/api/eels/svd",
                "EELS Advanced",
                ("eels_svd",),
                "curve ×k + map ×k",
                "shipped",
                "denoise mode has no op (payload kind would depend on a param — "
                "ADR 0005 wave-D addendum)",
            ),
            Row(
                "POST",
                "/api/eels/align-zlp",
                "EELS Advanced",
                ("eels_align_zlp",),
                "map + scalar ×2",
                "shipped",
                "derived SI cube; shift diagnostics ride derived.metadata "
                "(savgol_derivative precedent)",
            ),
            Row(
                "POST",
                "/api/eels/subpixel-align",
                "EELS Advanced",
                ("eels_subpixel_align",),
                "map + scalar ×2",
                "shipped",
                "derived SI cube; diagnostics in derived.metadata",
            ),
            Row(
                "POST",
                "/api/eels/richardson-lucy",
                "EELS Advanced",
                ("eels_richardson_lucy",),
                "curve ×2 + scalar",
                "shipped",
            ),
            Row(
                "POST",
                "/api/eels/maps",
                "Elemental workspace",
                ("eels_maps",),
                "map ×N",
                "shipped",
                "per-species method collapses to one shared choice and background "
                "is all-or-nothing (the eds_element_maps divergence precedent)",
            ),
            Row(
                "POST",
                "/api/eels/auto-assign",
                "Elemental workspace",
                ("eels_auto_assign",),
                "table",
                "shipped",
            ),
            Row(
                "POST",
                "/api/analyze/elnes",
                "EELS workshop",
                ("elnes",),
                "curve",
                "shipped",
                "optional reference_id overlay mode has no op (optional-input "
                "omission rule, ADR 0005 wave-D addendum)",
            ),
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
            Row(
                "POST",
                "/api/eds/zeta",
                "EDS Model Fit",
                ("eds_zeta",),
                "fit + table + scalar",
                "shipped",
                "mass-thickness scalar carries its counting-statistics sigma in- "
                "envelope (§5)",
            ),
            Row(
                "POST",
                "/api/eds/continuum",
                "EDS Model Fit",
                ("eds_continuum",),
                "fit + curve",
                "shipped",
            ),
            Row(
                "POST",
                "/api/eds/artifacts",
                "— (wrapper only, no GUI caller)",
                ("eds_artifacts",),
                "curve ×2 + table",
                "shipped",
                "headless reach is this endpoint's ONLY reach",
            ),
            Row(
                "POST",
                "/api/eds/recalibrate",
                "EDS Model Fit",
                ("eds_recalibrate",),
                "fit (calibration)",
                "shipped",
                "the derived DataStruct IS the application (apply dropped); "
                "optional pairs mode has no op (optional-input omission — the "
                "first non-coordinate pair list to meet gap 2)",
            ),
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
            Row(
                "POST",
                "/api/eds/auto-assign",
                "EDS Quantify panel, Maps tab",
                ("eds_auto_assign",),
                "table",
                "shipped",
            ),
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
                ("diffraction_detect",),
                "table + overlay",
                "shipped",
                "op flattens the rect/circle _Roi to a roi_kind discriminator "
                "+ NaN-sentinel groups; a roi_kind without its coordinates is "
                "an error, never a silent whole-image analysis (deliberate "
                "tightening, ADR 0005 wave-C addendum)",
            ),
            Row(
                "POST",
                "/api/diffraction/index",
                "Diffraction workshop",
                ("diffraction_index",),
                "table",
                "shipped",
                "`spots` rides a RowSpec list param, 1-based (row, col); the "
                "ROI re-centring is lifted to calc/diffraction_index.py. "
                "centre/measured_r stay in the FULL-image frame (they drive "
                "the whole-image ring overlay) while indexing uses the ROI "
                "frame. A degenerate ROI now errors instead of silently "
                "indexing everything with a shrunken d-scale",
            ),
            Row(
                "POST",
                "/api/diffraction/calibrate",
                "Diffraction calibration",
                ("diffraction_calibrate",),
                "fit + scalar ×2",
                "shipped",
                "op anchors d via d_known_ang or standard_phase + "
                "hkl_h/k/l NaN-sentinel floats (validated whole numbers); "
                "the anchor scalars are absent — not null — when unresolved",
            ),
            Row(
                "POST",
                "/api/analyze/simulate",
                "Diffraction simulation",
                ("diffraction_simulate",),
                "table + map + scalar",
                "shipped",
                "no image subject — op ignores `ds` (distribution_fit "
                "precedent); the rendered pattern inlines as a `map` "
                "envelope while the route registers a session image only "
                "when parented",
            ),
        ),
    ),
    Domain(
        "Measurement",
        (
            Row(
                "POST",
                "/api/measure/profile",
                "Measure panel, Stage",
                ("line_profile",),
                "curve + scalar",
                "shipped",
                "optional polyline points mode (a different calc function) has no "
                "op (optional-input omission rule)",
            ),
            Row(
                "POST",
                "/api/measure/roi",
                "Measure panel",
                ("roi_stats",),
                "scalar set",
                "shipped",
                "rect is 1-based INCLUSIVE — not diffraction's 0-based half-open, "
                "not the corner-ROI string",
            ),
            Row(
                "POST",
                "/api/measure/box-profile",
                "Measure panel",
                ("box_profile",),
                "curve ×2",
                "shipped",
            ),
            Row(
                "POST",
                "/api/measure/distance-tilted",
                "— (wrapper only, no GUI caller)",
                ("tilted_distance",),
                "scalar set",
                "shipped",
                "headless reach is this endpoint's ONLY reach; calibrated "
                "scalars absent — not null — when uncalibrated",
            ),
            Row(
                "GET",
                "/api/image/{img_id}/spectrum",
                "Spectrum panel",
                ("sum_spectrum",),
                "curve",
                "shipped",
                "a half-given or fractional region errors instead of silently "
                "summing the whole cube (strict-ROI discipline)",
            ),
            Row(
                "GET",
                "/api/image/{img_id}/histogram",
                "Histogram panel",
                ("intensity_histogram",),
                "curve",
                "shipped",
            ),
            Row(
                "POST",
                "/api/calibration/detect-bar",
                "Calibration dialog",
                ("scalebar_detect",),
                "scalar set",
                "shipped",
                "zero params — the route's reused request model's other fields "
                "are dead here and not mirrored (efd_similarity precedent)",
            ),
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

#: The EXPLICIT infrastructure allowlist: session, project, render,
#: export, jobs, calibration-store and dataset plumbing. This is an
#: allowlist, never a derived remainder — several route families
#: (`/api/image/...`, `/api/calibration/...`, `/api/filter`) mix analysis
#: and plumbing, so an "everything else is infrastructure" rule would let
#: a new analysis sibling in those families vanish from the audit while
#: the parity counts still looked complete. Any live route in none of the
#: three classifications fails the build.
INFRASTRUCTURE: tuple[tuple[str, str], ...] = (
    ("GET", "/api/batch/operations"),
    ("POST", "/api/batch/run"),
    ("GET", "/api/calibration"),
    ("POST", "/api/calibration"),
    ("POST", "/api/calibration/apply"),
    ("POST", "/api/calibration/clear"),
    ("DELETE", "/api/calibration/{key:path}"),
    ("POST", "/api/composite/register"),
    ("GET", "/api/debug/report"),
    ("GET", "/api/dev/sample-files"),
    ("POST", "/api/diffraction/phases/import"),
    ("DELETE", "/api/diffraction/phases/{name}"),
    ("POST", "/api/export"),
    ("POST", "/api/export/batch"),
    ("POST", "/api/export/figure"),
    ("POST", "/api/export/gif"),
    ("POST", "/api/export/table"),
    ("GET", "/api/fourd"),
    ("DELETE", "/api/fourd/{fourd_id}"),
    ("GET", "/api/fourd/{fourd_id}/meta"),
    ("POST", "/api/fourd/{fourd_id}/reshape"),
    ("GET", "/api/health"),
    ("WS", "/api/ws"),
    ("DELETE", "/api/image/{img_id}"),
    ("GET", "/api/image/{img_id}/data16"),
    ("POST", "/api/image/{img_id}/explode"),
    ("GET", "/api/image/{img_id}/meta"),
    ("POST", "/api/image/{img_id}/metadata"),
    ("POST", "/api/image/{img_id}/rename"),
    ("GET", "/api/image/{img_id}/render"),
    ("GET", "/api/image/{img_id}/rgb8"),
    ("GET", "/api/image/{img_id}/tile"),
    ("GET", "/api/image/{img_id}/tile-info"),
    ("GET", "/api/image/{img_id}/usermeta"),
    ("POST", "/api/image/{img_id}/usermeta"),
    ("GET", "/api/image/{img_id}/usermeta/sidecar"),
    ("DELETE", "/api/jobs/{job_id}"),
    ("GET", "/api/jobs/{job_id}"),
    ("GET", "/api/metadata-schema"),
    ("POST", "/api/project/load"),
    ("POST", "/api/project/relocate"),
    ("POST", "/api/project/save"),
    ("GET", "/api/region-sets"),
    ("POST", "/api/region-sets/replace"),
    ("GET", "/api/results"),
    # Query and composition over ALREADY-persisted records — they run no
    # analysis and produce no new science, so they are infrastructure like
    # the rest of the results surface, not an unregistered operation.
    ("POST", "/api/results/compare"),
    ("POST", "/api/results/export"),
    ("POST", "/api/results/report"),
    ("DELETE", "/api/results/{result_id}"),
    ("GET", "/api/results/{result_id}"),
    ("GET", "/api/results/{result_id}/outputs/{index}/data"),
    ("GET", "/api/session/images"),
    ("GET", "/api/session/launch-dir"),
    ("POST", "/api/session/open"),
    ("POST", "/api/session/open-folder"),
    ("POST", "/api/session/open-raw"),
    ("GET", "/api/session/supported-extensions"),
    ("POST", "/api/session/upload"),
    ("POST", "/api/usermeta/batch-autofill"),
    ("POST", "/api/watch/start"),
    ("GET", "/api/watch/status"),
    ("POST", "/api/watch/stop"),
    ("GET", "/api/workspaces"),
    ("POST", "/api/workspaces/load"),
    ("POST", "/api/workspaces/save"),
    ("DELETE", "/api/workspaces/{slug}"),
)

WAVE_LABEL = {
    "shipped": "shipped",
    "A": "wave A",
    "B": "wave B",
    "C": "wave C",
    "D": "wave D",
    "parked": "parked (item 8/9)",
}


# ── introspection ────────────────────────────────────────────────────


def app_routes() -> set[tuple[str, str]]:
    """(method, path) for every API endpoint the app serves.

    Covers HTTP routes AND WebSocket routes (as method ``"WS"``) — the
    lifecycle socket `/api/ws` is a real endpoint and a future analysis
    surface could arrive as one, so the total-classification guarantee
    must see them. Deliberately out of scope: FastAPI's own docs routes
    (`/docs`, `/redoc`, `/openapi.json`) and the static SPA mount, which
    are framework plumbing, not application endpoints.
    """
    from fastapi.routing import APIRoute, APIWebSocketRoute

    from fermiviewer.server import create_app

    found: set[tuple[str, str]] = set()

    def visit(routes: list, prefix: str) -> None:
        for route in routes:
            if isinstance(route, APIRoute):
                for method in (route.methods or set()) - {"HEAD", "OPTIONS"}:
                    found.add((method, prefix + route.path))
            elif isinstance(route, APIWebSocketRoute):
                found.add(("WS", prefix + route.path))
            elif hasattr(route, "original_router"):
                # FastAPI's lazily-included router wrapper: recurse with
                # the include-time prefix applied.
                inner_prefix = getattr(route.include_context, "prefix", "") or ""
                visit(route.original_router.routes, prefix + inner_prefix)

    visit(create_app().routes, "")
    return found


def curated_analysis() -> list[Row]:
    return [row for domain in DOMAINS for row in domain.rows]


def cross_check(live: set[tuple[str, str]]) -> None:
    """Fail loudly on any drift between the app, the registry, and the
    curated classification — this is what makes the audit trustworthy."""
    rows = curated_analysis()
    analysis = {(row.method, row.path) for row in rows}
    reference = set(REFERENCE)
    infra = set(INFRASTRUCTURE)

    overlap = sorted((analysis & reference) | (analysis & infra) | (reference & infra))
    if overlap:
        raise SystemExit(f"routes classified more than once: {overlap}")

    stated = analysis | reference | infra
    missing = sorted(stated - live)
    if missing:
        raise SystemExit(f"classified routes not served by the app: {missing}")

    # TOTAL classification: infrastructure is an allowlist, so any route
    # nobody stated fails here — a new analysis endpoint cannot hide as
    # plumbing while the parity counts still look complete.
    unclassified = sorted(live - stated)
    if unclassified:
        raise SystemExit(
            "live routes with no classification in tools/gen_coverage_table.py "
            f"(add to a Domain, REFERENCE, or INFRASTRUCTURE): {unclassified}"
        )

    registered = {spec.name for spec in fvops.list_ops()}
    for row in rows:
        unknown = sorted(set(row.ops) - registered)
        if unknown:
            raise SystemExit(f"{row.path} names unregistered op(s): {unknown}")
        if row.wave not in WAVE_LABEL:
            raise SystemExit(
                f"{row.path}: wave {row.wave!r} is not an assignment — every "
                f"analysis row needs one of {sorted(WAVE_LABEL)}"
            )
        # "shipped" is not independent state — it MEANS op-backed. A row
        # that breaks the equivalence would silently corrupt the headline
        # parity counts while both drift tests stayed green.
        if (row.wave == "shipped") != bool(row.ops):
            raise SystemExit(
                f"{row.path}: wave {row.wave!r} contradicts its op list "
                f"{row.ops!r} — 'shipped' if and only if a registered op "
                f"backs the route"
            )


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
    waves = {key: sum(1 for r in rows if r.wave == key) for key in ("A", "B", "C", "D", "parked")}
    n_ops = len(fvops.list_ops())
    return [
        f"- **{len(live)}** HTTP endpoints; **{len(rows)}** perform analysis, "
        f"{len(REFERENCE)} are physics-table lookups, and "
        f"{len(INFRASTRUCTURE)} are allowlisted infrastructure.",
        f"- **{opped} of {len(rows)}** analysis endpoints are backed by a "
        f"registered op (the `/api/filter` row alone carries {len(FILTER_OPS)}); "
        f"the registry holds **{n_ops}** ops in total.",
        "- Registered-op reach IS headless reach: batch recipes, folder "
        "watch, `fv --script`, and the Python API all resolve steps through "
        "the same registry and cannot call anything else.",
        f"- Remaining item-3 work: wave A ({waves['A']}), wave B "
        f"({waves['B']}), wave C ({waves['C']}), wave D ({waves['D']}) "
        f"endpoints; {waves['parked']} are parked behind the item-8/9 "
        "activation gates. Item 3 does not close while any analysis row "
        "lacks a wave or a named gate — every endpoint is assigned, none "
        "is silently deferred.",
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


#: Curated context for a stranded op, rendered only while that op is
#: actually in the list below — prose about a specific op must not
#: outlive the introspection that governs its row.
STRANDED_OP_NOTES = {
    "image_stats": "reaches the GUI only via `/api/export/table`",
}


def _ops_without_routes() -> list[str]:
    referenced = {name for row in curated_analysis() for name in row.ops}
    stranded = [spec for spec in fvops.list_ops() if spec.name not in referenced]
    lines = [
        "## Registered ops with no route",
        "",
        "Reachable from batch/Python but absent from the GUI's own wiring.",
        "",
    ]
    for spec in stranded:
        note = STRANDED_OP_NOTES.get(spec.name)
        suffix = f" ({note})" if note else ""
        lines.append(f"- `{spec.name}` — {_cell(spec.summary)}{suffix}")
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
    live = app_routes()
    cross_check(live)
    infra = sorted(INFRASTRUCTURE, key=lambda pair: (pair[1], pair[0]))

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
        "record/replay uses the same registry where its narrower wire-call "
        "translation table has an explicit mapping; other recorded calls "
        "remain replay-only (`frontend/src/lib/macroOpMap.ts`).",
        "",
        "Route and op inventories are read live from the app and registry "
        "at generation time; classifications are curated in "
        "`tools/gen_coverage_table.py`. Every live route must be classified "
        "— analysis, reference, or allowlisted infrastructure — so ANY new "
        "route without a classification fails the build, and "
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
            "dataset plumbing — outside the parity audit's scope. An "
            "explicit allowlist: a new route that is not added here (or "
            "classified as analysis/reference) fails the generator.",
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
