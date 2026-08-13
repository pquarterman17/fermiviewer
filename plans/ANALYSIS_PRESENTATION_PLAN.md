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
**Updated:** 2026-08-12 — wave 3 same day: items 4 (SVG/DPI chart
export) and 8 (scripting-reach sweep) shipped; item 3 ticked its
fit-view checkbox (model-confidence bands), leaving only its
radial/line-profile checkbox open. Gate 2060 backend / 1424 vitest.
Earlier waves same day: 1/2/5 (gate 1994/1319), then 6/7 + item 3's
first chart (gate 2026/1374). All three waves via file-disjoint sonnet
worktree agents. **Open: item 3's last checkbox + Tier 3 (9–12,
build-on-demand only).**

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
   `value ± err` text (`lib/formatUncertainty.ts`).
   **First chart SHIPPED 2026-08-12:** the composition profile draws a
   real ±1σ band per element (see Completed for the machinery — the
   reusable `lib/charts/sigmaBand.ts` helper and the backend σ
   propagation pattern). Remaining: the other σ-carrying charts —
   - [x] EELS/EDS fit views: model-confidence band from the covariance —
         SHIPPED 2026-08-12, see the wave-3 Completed entry
   - [ ] radial/line-profile charts where a σ series exists or is cheap
   - [ ] spectrum integration readouts stay text (scalars, not series) —
         explicitly out


## Tier 2 — Medium Impact

*(empty — items 5–8 all shipped 2026-08-12; see Completed)*

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

- **#3 (fit-view checkbox): model-confidence bands** (2026-08-12; item
  stays OPEN for radial/line-profile charts only) — new pure
  `calc/spectral_fit.model_sigma()`: central-difference Jacobian
  (rel_step 1e-6, scipy's own heuristic) then
  `sqrt(diag(J·cov·Jᵀ))` via `np.einsum("ij,jk,ik->i", ...)` without
  materialising the point-space product. Pinned by a CLOSED-FORM test:
  for y=a+b·E the band must equal `sqrt(var_a + E²·var_b + 2E·cov_ab)`
  to rtol 1e-9 (linear ⇒ zero truncation error) — dropping the
  covariance cross-term by mutation produced up to 169 % error and a red
  test. Serialised additively as `model_sigma` on `/eels/fit`,
  `/eds/peakfit`, `/eds/zeta` (null on failed fit / non-finite
  covariance) — a covariance-derived trace is the one thing the client
  cannot reconstruct, so serialising it IS item 2's rule, and the route
  docstrings say so. Both fit plots shade model ±1σ via the existing
  `sigmaBand.ts`. The EELS overlay turned out to live in
  `EelsWorkshop.tsx`, not `EelsResults.tsx` — extracted to
  `eels/EelsFitOverlayPlot.tsx` (EelsWorkshop 364 → 248), mirroring the
  `EdsModelFitPlot` split. mypy caught a real variable-shadowing bug
  (loop-local `sigma` colliding with the Fano width). +8 backend / +10
  frontend tests. WATCH: `routes/eds_advanced.py` now 493/500.

- ~~**#4 Vector (SVG) chart export + DPI control**~~ (2026-08-12) —
  built ONCE inside `PlotContextSurface` (which already holds every
  chart's live uPlot ref), so all analysis charts gained "Export SVG
  (vector)" + 300/600 dpi PNG with ZERO per-chart wiring. New pure
  `lib/charts/chartSvg.ts` (481) + `ticks.ts` (1-2-5 ladder, log ticks)
  + `chartRaster.ts` (SVG→PNG at dpi scale) — reads only PUBLIC uPlot
  state (data/series/scales incl. per-series stroke functions and
  `distr:3` log detection; a real consumer, the PSD chart, is log-log),
  resolves CSS `var(--token)` strokes via getComputedStyle, and uses a
  fixed white/paper background regardless of app theme (the line-chart
  publication convention; deliberately different from figureExport's
  dark micrograph convention — both "fixed regardless of theme").
  V1 limits documented in the module header, not silently divergent:
  custom canvas draw-hooks (window shading, error caps) are not
  reproduced, and σ-band boundary series are recognised and DROPPED
  rather than drawn as spurious lines. Null-gap path-breaking and
  invisible-series filtering mutation-verified. +35 frontend tests.

- ~~**#8 Batch + scripting reach for existing analyses**~~ (2026-08-12)
  — survey-first sweep: 5 new ops in a new `ops/catalogue_analysis.py`
  (379): `eels_fit`, `eds_peakfit`, `eds_element_maps`,
  `composition_profile` (compound: quantify + line-sample in one call,
  since scripts have no pre-registered map ids), `distribution_fit`.
  Shared `ops/_parsing.py` extracted from catalogue_spectral rather than
  copied. Scripting reach VERIFIED, not assumed: `Image.__getattr__`
  auto-dispatches registered ops, proven by an end-to-end test calling
  `img.eds_peakfit(elements="Fe")` on a real .msa via `fv.open()`.
  **The recorded boundary** (why the rest is not registered): `eds_zeta`
  deferred (next natural op); per-pixel `fit_edges_map` doesn't fit the
  one-derived-image OpResult contract; `eds_recalibrate` is stateful;
  session/jobs/watch/project/export routes are stateful or have their
  own scripting path (`Result.to_csv`). api-reference regenerated.
  +26 backend tests (all op-vs-calc parity).

- ~~**#6 Population histograms + distribution fitting**~~ (2026-08-12) —
  new pure `calc/distributions.py` (summary stats; normal/lognormal/
  weibull via `scipy.stats` with `floc=0` for the latter two so all fits
  have k=2; `best` by lowest AIC; KS statistic + p per fit;
  Freedman–Diaconis bins with degenerate-IQR fallback; N≥8 to fit,
  non-finite values dropped and counted) + thin `POST
  /api/analyze/distribution` (`routes/distributions.py`). Shared
  `PopulationHistogram.tsx` (bars + pdf overlay scaled `pdf·N·binWidth`,
  mutation-pinned; selector defaults to Best; <8 objects auto-falls back
  to histogram-only) wired into BOTH particle and grain results on
  equivalent diameter — calibrated units only when EVERY object has one,
  else px, never a fake unit or a mix. **Grains needed a payload fix the
  audit-style verification exposed:** per-grain `equiv_diameter_px` was
  computed but never serialised (only the scalar mean was), so the
  distribution genuinely could not be drawn before. Quartiles are
  Hyndman–Fan Type 7 in all three implementations (calc, chart lib,
  `measureStats.ts` — which finally gained median/quartiles).
  +36 backend / +25 frontend tests, AIC-selection and pdf-scaling
  mutation-verified both sides. NOTE: `routes/structure.py` sits at
  exactly 500/500 after the payload addition — the next touch there MUST
  extract, not shave.

- ~~**#7 Fit-report export: params ± σ + fit stats to CSV**~~
  (2026-08-12) — pure `lib/spectrum/fitReport.ts`
  (`eelsFitReportToCsv`/`edsFitReportToCsv`) sharing the quant exports'
  exact precision-7 formatter and `downloadCsv` seam, so a number
  appearing in both exports cannot render two ways. Header: image, fit
  window, R², χ²ᵣ, convergence; one row per edge/element with fitted
  param ± 1σ, net area, at%/wt% when present. Buttons in `EelsResults`
  and `EdsModelFit` (the latter's plot extracted to `EdsModelFitPlot.tsx`
  — 504 → 380, the ratchet forcing a module again). Backend additive:
  `/eels/fit` now serialises `onset_ev` and `fit_range` (computed
  internally, never exposed — the report needed both; χ²ᵣ/R² were
  already there from item 2). +3 backend / +9 frontend tests,
  value/error column swap mutation-verified.

- **#3 (first slice): composition-profile ±1σ band** (2026-08-12; item
  stays OPEN for the remaining charts) — `composition_profile_sigma()`
  in `calc/eds_maps.py` reuses `calc/uncertainty.py`'s
  `cliff_lorimer_uncertainty` (the SAME delta-method core `/eds/quantify`
  uses — no second error model), sampling net + gross (`bg="none"`)
  count maps through identical line geometry with `var(I_net) ≈ I_gross`
  (the module's documented Egerton approximation). Route serialises
  `atomic_percent_error` additively and best-effort (σ failure never
  fails the profile; only cube-resolution HTTPException is caught).
  Reusable `lib/charts/sigmaBand.ts` (uPlot bands + hidden hi/lo series,
  NaN-σ → no band at that point) so item 3's remaining charts inherit
  the machinery. **Two real bugs found:** the frontend was passing a
  derived at% MAP id as the route's `image_id` (the SI cube was never
  reachable from that call — fixed, `analyzeCompositionProfile` now
  takes an explicit `cubeId`), and the synthetic generator's uint16
  rescale ceiling collapses any cube with peak λ > 62000 to the same
  effective counts (plus `build()`'s fixed output filename silently
  overwrites across builds). Honesty checks: truth within ±3σ at the
  pure ends (no widening needed); σ scales as counting statistics
  (measured 2.002 vs theoretical 2.0 on a ×4-counts cube). +3 backend /
  +21 frontend tests, band pairing and σ positivity mutation-verified.

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
