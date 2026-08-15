# Shape Identification

Gives segmented objects a shape identity. The 2026-08-14 audit found a
sharp asymmetry: the segmentation substrate is rich (multi-Otsu, watershed
×2, SLIC, RF-trained grains, NCC template matching, contour tracing with
holes) and `GrainStats` already carries eccentricity/orientation/solidity/
Crofton perimeter — but `RegionStats` (particles) carries **no shape
descriptor at all**, so the app cannot answer the canonical TEM morphology
question: *spheres or rods?* Meanwhile `calc/distributions.py` is
deliberately metric-agnostic, so every descriptor added becomes a fittable
population for free.

**Status:** Active (created 2026-08-14; Wave 1 items #1–#5 in flight as a
three-agent parallel build)
**Parent:** MAIN_PLAN.md
**Created:** 2026-08-14

Scope rule (inherited from ANALYSIS_PRESENTATION_PLAN's audit ruling):
image-derived measurements only. All items below measure segmented regions
of the image; none is general-purpose statistics or graphing.

---

## Conventions (normative — read before implementing anything)

These exist because the 2026-08-14 Tier-2 builds went three-for-three on
"correct math, wrong units/label claim". Shape metrics have the same trap
surface. Every one of these is a decision already made — do not re-decide.

1. **skimage `regionprops` is the metric source**, matching
   `grains.grain_stats` exactly (`perimeter_crofton`, `eccentricity`,
   `orientation`, `solidity`, `axis_major_length`, `axis_minor_length`,
   `feret_diameter_max`). Do not hand-roll moments the library already
   computes under test.
2. **Circularity = 4πA / P² with P = the CROFTON perimeter.** The naive
   polygonal pixel-boundary perimeter overestimates digitized circles and
   yields ≈0.79 for a perfect disk — the classic trap. With Crofton a
   large digitized disk approaches 1. Small regions can still exceed 1
   slightly (Crofton bias); report the raw value and document it — never
   clip silently. Pin with tests: large synthetic disk → ≈1 (±few %),
   filled square → π/4 ≈ 0.785.
3. **Orientation: skimage convention, verbatim** — the angle between the
   ROW axis (axis 0) and the ellipse major axis, range (-π/2, π/2],
   radians on the wire. This is AXIAL data (period π, a rod at +80° is
   the same rod at −100°): any histogram/rose spans exactly (-90°, 90°]
   and is never mirrored into a full circle (mirroring double-counts
   visually). It is MORPHOLOGICAL orientation, not crystallographic —
   `crossSectionReport.ts` already draws this distinction; keep its
   wording.
4. **Aspect ratio = axis_major / axis_minor** of the binary moment
   ellipse. Degenerate minor axis (single-pixel line) → `null` on the
   wire, never Infinity and never a silent large number.
5. **Calibration follows the existing `*_calibrated` pattern**
   (`RegionStats.area_calibrated`): lengths get a `_calibrated` twin that
   is real when the image has a pixel size and follows the SAME
   missing-value serialization the particles route already uses for
   `diameter_calibrated` — read that code path first and copy it; do not
   invent a new null convention. Dimensionless metrics (circularity,
   eccentricity, solidity, aspect ratio) have no calibrated twin —
   adding one would be a units error.
6. **Shape classes are advisory heuristics on a 2D PROJECTION.** A rod
   viewed end-on projects as a disk; no 2D image can refute that. Classes
   therefore claim morphology of the projection only, the thresholds are
   visible and caller-tunable (never hidden), and nothing is auto-
   corrected or filtered by class — same advisory philosophy as the
   species-overlap ⚠ badge. Docstring AND GUI tooltip both carry the
   projection caveat.
7. **Positional wire fields stay 1-based** (MATLAB heritage:
   `RegionStats.centroid`/`bbox`). New descriptors are lengths, ratios
   and angles — coordinate-origin-free — so nothing new is positional; if
   an item ever adds a positional field, it is 1-based like its
   neighbours.

## Frozen wire contract (Wave 1)

Frontend and backend build against this in parallel; the field names and
meanings below are normative. If implementation proves a field wrong,
STOP and report — do not rename unilaterally.

Each element of the particles response (`/analyze/particles` family,
route in `routes/structure.py`) gains:

```
circularity: float        # 4πA/P_crofton², dimensionless, may slightly exceed 1
aspect_ratio: float|null  # axis_major/axis_minor; null when degenerate
eccentricity: float       # moment-ellipse eccentricity, [0, 1)
orientation_rad: float    # skimage convention, (-π/2, π/2], axial
solidity: float           # area / convex-hull area, (0, 1]
feret_max: float          # max caliper diameter, px
feret_max_calibrated: ?   # same serialization as diameter_calibrated
shape_class: "sphere-like" | "rod-like" | "intermediate" | "aggregate"
```

Classification (defaults; request may override via optional
`class_thresholds: {aggregate_max_solidity, rod_min_aspect,
sphere_max_aspect, sphere_min_circularity}`):

```
aggregate    solidity < 0.85          # checked FIRST — trumps the rest
rod-like     aspect_ratio ≥ 2.5
sphere-like  aspect_ratio < 1.3 AND circularity > 0.85
intermediate otherwise (incl. null aspect_ratio)
```

Wave-2 endpoints (new module `routes/shape_id.py`; names normative):

```
POST /analyze/efd-similarity   # mirror of the particles request + ref_id
  → {ranked: [{id, distance}], n_harmonics}
POST /analyze/fit-shape        # {points: [[row,col],...]} 1-based, closed ring
  → {circle: {cy,cx,r,rms}, ellipse: {cy,cx,a,b,theta_rad,rms}}   # px, 1-based
```

## File ownership (Wave 1 — collision-avoidance matrix)

Three agents build in parallel in isolated worktrees. A file appears in
exactly one column; CHANGELOG.md and plans/ belong to the integrator
only (three agents editing `## [Unreleased]` is a guaranteed 3-way
conflict).

| A1 (backend metrics)        | A2 (backend shape-ID)      | A3 (frontend)                  |
|-----------------------------|----------------------------|--------------------------------|
| calc/shape_metrics.py (new) | calc/efd.py (new)          | lib/api/imaging.ts (types)     |
| routes/structure.py         | calc/shape_fit.py (new)    | ParticlesMode.tsx              |
| tests/test_shape_metrics.py | routes/shape_id.py (new)   | analysis/OrientationRose.tsx   |
| tests/test_api_particles_*  | server_routers.py (1 line) | + colocated vitest files       |
|                             | tests/test_efd.py etc.     |                                |

## Tier 1 — Wave 1 (parallel build 2026-08-14)

1. **Particle shape descriptors** — `calc/shape_metrics.py` (pure):
   per-region descriptor arrays from `regionprops_table` + derived
   circularity/aspect-ratio per Conventions 1–5. Route merges them into
   the existing particles response (additive; nothing existing renamed).
   - [ ] calc module + pure tests (disk ≈1 / square π/4 pins mandatory)
   - [ ] route extension + API tests
2. **Shape classes + aggregate flag** — `classify_shapes` in the same
   calc module per the frozen thresholds; `shape_class` on the wire.
   - [ ] classifier + boundary tests (each threshold edge, both sides)
   - [ ] tunable thresholds honoured end-to-end through the route
3. **Frontend: columns, metric picker, orientation rose** —
   ParticlesMode table gains circularity/AR/class columns; the existing
   PopulationHistogram feed gains a metric picker (equiv ⌀ /
   circularity / aspect ratio / Feret max — unit string switches with
   calibration exactly as `pickSizeValues` does); new `OrientationRose`
   SVG half-rose (axial, Convention 3) with near-circular regions
   (eccentricity < 0.2) excluded from the rose and counted in a note,
   since a circle's orientation is noise; per-class count line with the
   projection-caveat tooltip.
   - [ ] table + picker + rose + per-class counts, all against the
         frozen contract with mocked responses

## Tier 2 — Wave 2 (sequential, after Wave-1 merge)

4. **Elliptic Fourier shape signatures** — `calc/efd.py` (pure): Kuhl &
   Giardina harmonic coefficients of the traced closed contour
   (`calc/contours.py` provides the rings), normalized for scale /
   rotation / start point; similarity = L2 in normalized-descriptor
   space. `/analyze/efd-similarity` recomputes the segmentation from the
   mirrored request (routes are stateless — same recompute pattern the
   app already uses) and ranks all regions against `ref_id`. GUI wiring
   ("find similar") lands in Wave 2 to avoid colliding with A3.
5. **Circle/ellipse fitting** — `calc/shape_fit.py` (pure): direct
   least-squares circle + ellipse fits on contour points, for pores and
   core-shell shells. `calc/diffraction_calib.py` already fits ellipses
   to diffraction rings — READ IT FIRST and reuse/extract rather than
   re-derive; a second independent ellipse fit in the same codebase is a
   defect. `/analyze/fit-shape` per the contract. Also the geometry
   runway for parked PLAN_4DSTEM #10 (Bragg-disk detection).

## Testing & integration protocol (Wave 1)

- Worktree agents run ONLY scoped checks: `ruff`, `mypy`, and their own
  test files. The full backend (~2min15s) and frontend (~85s) suites are
  the INTEGRATOR's job, run once per merge, sequentially — two suites
  running concurrently on this machine starve the CPU and mass-fail the
  frontend with bogus `getContext()` errors.
- Mutation-test every new test (scoped runs): break the code, see RED,
  restore. A test never seen failing is not evidence.
- Integration order: A1 → full gate → A2 → full gate → A3 → full gate →
  CHANGELOG + plan strikes by the integrator. A1 merges first because A3
  types its wire fields.

## Completed

(nothing yet)
