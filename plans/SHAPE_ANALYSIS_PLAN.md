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

**Status:** Active (created 2026-08-14; same-day: Wave 1 (#1–#3) fully
SHIPPED and integrated, #4/#5 backend SHIPPED + skip-and-note refinement
landed in the same day's bug round. Remaining: Wave 2 GUI wiring for
#4/#5 — the only open work in this plan)
**Parent:** MAIN_PLAN.md
**Created:** 2026-08-14
**Updated:** 2026-08-14 — Wave 1 integrated. Convention #2 corrected
during the build (square ≈0.874 Crofton, not π/4; sphere cutoff
0.85→0.92) — found by A1's honest implementation of the mandatory pin;
two integrator hardenings recorded under items #1/#2.

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
   perimeter underestimates a digitized disk's circularity (measured:
   ≈0.90 with skimage's chain-code `perimeter`); with Crofton a large
   digitized disk approaches 1. Small regions can still exceed 1
   slightly (Crofton bias); report the raw value and document it — never
   clip silently. Pin with tests: large synthetic disk → ≈1 (±few %),
   filled square → **≈0.874** (measured, converged over sides 21→1601).
   *CORRECTED 2026-08-14 during Wave 1:* this convention originally
   claimed the square pins at π/4 ≈ 0.785 — that is the NAIVE
   estimator's square value (where it happens to be exact), not
   Crofton's; 4-direction Crofton has a persistent bias on axis-aligned
   edges and never converges to π/4. Found by A1 implementing the pin
   honestly and reporting the discrepancy; verified independently by
   the integrator. Consequence: `sphere_min_circularity` moved
   0.85 → **0.92** — on the Crofton scale a square scores 0.874, so the
   original 0.85 cutoff would have classified a cube-projection as
   sphere-like, and cubes-vs-spheres is the canonical faceted-vs-round
   distinction. The cutoff now sits between the square's 0.874 and the
   large disk's ≈0.99, pinned by an end-to-end square→intermediate
   test that fails under the old default.
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
sphere-like  aspect_ratio < 1.3 AND circularity > 0.92   # was 0.85; see Convention #2's correction
intermediate otherwise (incl. null aspect_ratio)
```

Wave-2 endpoints (new module `routes/shape_id.py`; names normative):

```
POST /analyze/efd-similarity   # mirror of the particles request + ref_id
  → {ranked: [{id, distance}], skipped: [{id, reason}], n_harmonics}
  # skipped added 2026-08-14 (bug round): undescribable non-reference
  # regions skip-and-note instead of failing the query
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

~~**1. Particle shape descriptors**~~ (2026-08-14, agent A1 + integrator) —
   `calc/shape_metrics.py` (176 lines, pure) via `regionprops_table`
   matching `grain_stats`'s idiom; the 8 contract fields merged
   additively into `/analyze/particles`; `feret_max_calibrated` follows
   `_nan_none` exactly. 31 tests, 13-mutation kill matrix. The mandatory
   square pin exposed a plan error (see Convention #2's correction):
   Crofton measures a square at ≈0.874, not π/4.
   - [x] calc module + pure tests (disk ≈1 / square ≈0.874 pins)
   - [x] route extension + API tests
~~**2. Shape classes + aggregate flag**~~ (2026-08-14, agent A1 +
   integrator) — `classify_shapes` + `ClassThresholds`, aggregate checked
   first, boundary tests on every edge. Integrator hardening: sphere
   cutoff 0.85→0.92 (Convention #2 correction) with an end-to-end
   square→intermediate pin, and threshold defaults consolidated to the
   calc layer ONLY — the route's pydantic model briefly duplicated the
   literals and drifted on the first correction, so partial overrides
   silently reverted the sphere cutoff; route fields are now
   None-defaulted and resolved via `dataclasses.replace`, pinned by a
   probe square inside the 0.85–0.92 trap zone.
   - [x] classifier + boundary tests (each threshold edge, both sides)
   - [x] tunable thresholds honoured end-to-end through the route
~~**3. Frontend: columns, metric picker, orientation rose**~~
   (2026-08-14, agent A3) — ParticlesMode 192→284 lines: circ/AR/class
   columns (null AR renders "—"), metric picker over the
   PopulationHistogram feed via new `lib/populationHistogram.ts`
   (dimensionless metrics carry no unit; null ARs excluded and counted),
   new `OrientationRose.tsx` (177 lines, axial half-rose, +90° edge
   clamped, ecc<0.2 excluded with note), per-class count line with the
   projection-caveat tooltip. Typed verbatim against the frozen
   contract with mocks; the contract held at integration — live E2E
   found zero drift between A3's types and A1's real wire. Also fixed a
   latent fixture bug in the pre-existing ParticlesMode tests (a mock
   crashing `ingestDerived`, invisible because the old tests never
   asserted past the call args).
   - [x] table + picker + rose + per-class counts, all against the
         frozen contract with mocked responses

## Tier 2 — Wave 2 (sequential, after Wave-1 merge)

4. **Elliptic Fourier shape signatures** — *backend SHIPPED 2026-08-14
   (agent A2): `calc/efd.py` (256 lines, Kuhl & Giardina §IV
   normalization, `DEFAULT_N_HARMONICS = 10` visible constant) +
   `/analyze/efd-similarity` in new `routes/shape_id.py`; invariance
   tests (scaled/rotated/start-shifted copy → distance ≈0); the request
   model IMPORTS `ParticleRequest` (structure_grains precedent). EFD
   contour tracing runs finer than `trace_outer_contour`'s hand-edit
   default (0.5px/300 vertices — mutation-verified load-bearing).*
   Remaining:
   - [ ] Wave 2: workshop "find similar" control (was deferred from the
         parallel build to avoid colliding with A3 in ParticlesMode)
   - [x] ~~Wave 2 refinement: skip-and-note~~ (2026-08-14, bug round) —
         undescribable non-reference regions land in `skipped:
         [{id, reason}]` instead of failing the query; an undescribable
         REFERENCE still 422s ("nothing to rank against"). Both paths
         pinned red-first.
5. **Circle/ellipse fitting** — *backend SHIPPED 2026-08-14 (agent A2):
   `calc/shape_fit.py` (165 lines) REUSING `diffraction_calib`'s
   Halir–Flušser ellipse fit via import (already importable — no
   extraction needed); `/analyze/fit-shape` per the contract, pure
   delegation for point-count guards (route-level pre-checks were
   mutation-verified redundant and removed).* Also the geometry runway
   for parked PLAN_4DSTEM #10 (Bragg-disk detection). Remaining:
   - [ ] Wave 2: GUI wiring (fit a traced region/contour from the
         Regions/Particles surface)

## Wave 2 — GUI wiring (specced 2026-08-15, two parallel agents)

File partition (disjoint by construction):

| W2a (find similar)              | W2b (fit shape)                  |
|---------------------------------|----------------------------------|
| lib/api/imaging.ts (client)     | lib/api/regions.ts (client)      |
| ParticlesMode.tsx (+child)      | Inspector/RegionsCard.tsx        |
| colocated tests                 | colocated tests                  |

**W2a — "Find similar" in ParticlesMode.** A per-row action on the
particles table calls `/analyze/efd-similarity` with the SAME segmentation
params as the displayed run plus that row's id as `ref_id`. Result mode:
a distance column, rows sorted ascending by it (reference first at ≈0),
skipped regions kept visible with "—" and their reason on hover; a status
line "ranked N · skipped M"; an explicit exit control restores the normal
table. A 422 (undescribable reference) surfaces the server detail via the
existing status idiom. Distances are DIMENSIONLESS (normalized-descriptor
space) — no unit, ever.

**W2b — circle/ellipse fit in RegionsCard.** A per-region "Fit" action
sends the polygon's vertices to `/analyze/fit-shape` and shows both fits
compactly: circle (center, r, rms) and ellipse (center, a, b, θ shown in
DEGREES with the convention stated, rms). Both are shown with their rms —
advisory, the user judges; nothing auto-picks. Lengths (r, a, b, rms)
display calibrated when the image has a pixel size, px otherwise —
following the card's existing physical-units convention; rms IS a length
and calibrates with them. Coordinate care: measures hold `{x, y}`; the
endpoint wants 1-based `[[row, col]]` — the implementer must VERIFY the
measure/regions basing against `routes/regions.py` before converting, not
guess (fitting is translation-equivariant, so a basing error would be
invisible in r/a/b/rms and visible only in the reported center — exactly
the kind of silent unit bug this plan exists to prevent). No new overlay
machinery: draw the fitted shape only if an existing overlay path makes it
trivial, else numeric readout only.

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
