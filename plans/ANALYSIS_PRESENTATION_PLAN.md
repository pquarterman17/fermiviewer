# Analysis presentation plan — fits, charts, populations

Close the gaps in how FermiViewer's *own* analysis results are fitted,
displayed, and exported: computed uncertainties that no plot shows, fits
with no visible residuals, raster-only chart export beside a vector image
pipeline, Gaussian-only peak shapes, and measured populations that leave
the app as raw rows. Source: `docs/originpro-jmp-gap-audit.md` (scope
decision, owner, 2026-07-28: FermiViewer stays image-focused — the
DECLINED general-graphing/statistics list lives in that doc and is out).

**Status:** Active
**Parent:** MAIN_PLAN.md
**Created:** 2026-08-12
**Updated:** 2026-08-12 — items 1 (peak shapes), 2 (residuals + R²) and 5
(Savitzky–Golay) shipped the same day the plan was booked, via three
file-disjoint sonnet worktree agents; merged-tree gate 1994 backend /
1319 vitest, all green

---

## Context

### How the pieces fit together

Every item rides on infrastructure already in the tree — no new runtime
dependencies. The spectral engine is `calc/spectral_fit.py` (additive
`Component` model over an energy axis; `FitResult` already computes
`residual`, `reduced_chi2`, and full covariance) with consumers
`calc/eds_peakfit.py` (constrained multi-Gaussian EDS deconvolution) and
`calc/eels_model.py` (multi-edge EELS fits, served by
`routes/spectral_fit.py` → `/eels/fit`). Charts are uPlot throughout the
React frontend; the vector export pipeline for *images* is
`routes/export.py` + `routes/_export_svg.py`. Ops registration
(`ops/catalogue.py`, `ops/catalogue_spectral.py`) is what makes an
analysis reachable from macros, batch recipes, and `fermiviewer.api`
scripting. Measurement-population stats live in
`frontend/src/lib/measureStats.ts` and export as raw CSV rows.

Audit evidence was re-verified against main on 2026-08-12 before this
plan was booked: zero Voigt/Lorentzian shapes, zero `savgol` hits, no
σ band/fill on any chart, op catalogue at ~18 ops, no
median/quartile/distribution fit for populations.

### Data / control flow

```
spectrum/profile ─> calc engine (Components) ─> FitResult
                                                 ├─> params ± σ  ── shown as text today; #3 bands, #7 CSV report
                                                 └─> residual/χ²ᵣ ── computed, never serialised; #2 surfaces it
measured objects (particles/grains/measures) ─> stats ─> #6 histogram + distribution fit
any analysis chart ─> canvas PNG today ─> #4 SVG/DPI export (reuse _export_svg plumbing)
every new verb ─> ops registration ─> #8 batch/scripting reach for free
```

### Dependency map

- Items 1, 2 and 5 shipped 2026-08-12 (see Completed) — items 3 and 7
  are now unblocked.
- Item 3 (σ bands) follows 2's serialisation conventions (scalars
  server-side over the fit window; traces derived client-side from
  curves already on the wire).
- Item 7 (fit report CSV) consumes what 2 serialises.
- Item 4 (vector chart export) is independent of all of the above.
- Item 6 (population histograms) is independent; its backend half is a
  new `calc/distributions.py`.
- Item 8 (batch/scripting reach) is a sweep item — do last, after item
  6's new verbs exist, so the sweep covers them too (items 1 and 5
  already registered theirs: the spectral-fit shapes ride the existing
  fit routes, and savgol landed as ops from day one).

---

## Tier 1 — High Impact

3. **Error bars / ±σ bands on existing analysis charts** (was audit R1)
   — uncertainty is computed everywhere and rendered only as
   `value ± err` text (`lib/formatUncertainty.ts`); no uPlot band/fill
   anywhere. Start with charts whose payload already carries σ.

4. **Vector (SVG) chart export + DPI control for analysis plots** (was
   audit R2) — charts export via `canvas.toBlob("image/png")` at screen
   resolution; the image stage already has a vector pipeline to reuse.

## Tier 2 — Medium Impact

6. **Population histograms + distribution fitting for measured objects**
   (was audit R6) — particle/grain/measure populations export as raw
   rows; no median/quartiles, no normal/log-normal/Weibull fit
   (`scipy.stats.*.fit`). The one JMP-shaped feature squarely in-mission.

7. **Fit-report export: params ± σ + fit stats to CSV** (was audit R8) —
   CSV exists for quant tables only; completes the provenance story for
   fits the app already runs.

8. **Batch + scripting reach for existing analyses** (was audit R7) —
   op catalogue ≈18 ops, no spectral fitting; `fermiviewer.api` reaches a
   fraction of server capabilities. Sweep after 1/5/6 land their verbs.

## Tier 3 — Nice-to-Have

*(the audit's "only if the need recurs" tier — build on demand, not on
schedule)*

9. **Two-sample comparison of measured populations** (was audit R9) —
   t-test / Mann–Whitney on grain/particle stats; only if item 6 gets
   real use.

10. **Headless folder batch** (was audit R10) — `fv run recipe.json`
    over paths.

11. **Baseline options for spectra** (was audit R11) — SNIP / anchor
    spline; only if the joint-fit backgrounds prove insufficient for
    real ELNES work.

12. **Chart dark-mode theming** (was audit R12) — stock uPlot chrome
    ignores the app theme; cosmetic.

## Completed

- ~~**#1 Voigt / Lorentzian / pseudo-Voigt in the spectral engine**~~
  (2026-08-12) — new pure `calc/peak_shapes.py` (194 lines): `lorentzian`,
  `pseudo_voigt`, `voigt` Component builders in `gaussian`'s exact style
  (amp = peak height at center, documented σ↔γ FWHM matching for
  pseudo-Voigt, true Voigt height-normalised over
  `scipy.special.voigt_profile`) plus one analytic net-area helper per
  shape — the Voigt area is `amp/profile(0)`, falling straight out of
  scipy's unit-area normalisation. `spectral_fit.py` gained only
  `gaussian_area`; `eds_peakfit`'s hardcoded `amp·σ·√(2π)` now calls it
  (behaviour-preserving, original 11 tests pass unmodified), and
  `element_peak_component`/`fit_peaks`/`quantify_peaks` gained opt-in
  `lorentzian_hwhm_kev` (default 0.0 = byte-identical Gaussian path,
  pinned by test; >0 = fixed-γ Voigt with area accounting switched to
  `voigt_area`, amp-error propagated through the same linear scale).
  Tests: numeric-vs-analytic areas <0.5% via `np.trapezoid`, η=0/1 and
  γ→0 pointwise limits, a >1e10 tail-ratio mutation guard at 5×FWHM,
  Voigt/pseudo-Voigt fit round-trips, and a real S-K/Mo-L Voigt overlap
  (which needs `beam_kv=15` — at 200 kV Mo resolves to its K line).

- ~~**#2 Surface residuals + R² on existing fits**~~ (2026-08-12) —
  `/eels/fit`, `/eds/peakfit` and `/eds/zeta` now return `r_squared`;
  the residual trace is derived CLIENT-side (`lib/spectrum/fitQuality.ts`)
  from the measured/model curves already on the wire — a third array
  would duplicate them — while R² stays SERVER-side because it must be
  computed over the actual fit window, which the client cannot always
  reconstruct (EELS `fit_range` is a strict subset of the returned axis).
  New pure `calc/fit_quality.py` (plain unweighted 1−SS_res/SS_tot,
  `ctf.py`'s existing convention; degenerate SS_tot=0 → 0.0 not NaN, and
  the docstring pins the fit-window contract). UI: R² readout + residual
  sub-plot in `EelsResults` (own small uPlot with `time:false` — a shared
  y-axis with the spectrum would flatten residuals invisible), scalar
  readout row in `EdsModelFit`. +8 backend / +13 frontend tests, R² sign
  and residual subtraction verified by mutation on both sides.

- ~~**#5 Savitzky–Golay smoothing + derivative for spectra/profiles**~~
  (2026-08-12) — new pure `calc/smoothing.py` wrapping
  `scipy.signal.savgol_filter` (`savgol_smooth`, `savgol_derivative`;
  window/polyorder/order/delta validation, float64 out) + two ops in a
  new `"spectral"` category (`savgol`, `savgol_derivative`) so batch
  recipes, macros and `fermiviewer.api` scripting reach them with no
  further wiring. A SPECTRUM_IMAGE cube reduces via `sum_spectrum()`
  (the `eels_quantify` convention); the derivative's `delta` is op-layer
  policy — energy-axis scale when calibrated, else 1.0/channel,
  documented. Tests pin the classic polynomial-reproduction property
  (with a negative quartic check against a vacuous pass-through),
  analytic derivative with non-unit delta, and op-vs-calc parity on a
  2.0 eV/channel fixture so a `delta=1.0` regression fails.
  `docs/api-reference.md` regenerated. GUI exposure (a smooth/derivative
  toggle on the spectrum plots) is NOT part of this item — if wanted, it
  rides item 3's chart work.
