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
**Updated:** 2026-08-12

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

- Items 1 (shapes), 5 (Savitzky–Golay), and 2 (residuals) are
  independent and file-disjoint: 1 owns `calc/spectral_fit.py` +
  `calc/eds_peakfit.py`, 5 owns a new `calc/smoothing.py` +
  `ops/catalogue_spectral.py`, 2 owns `routes/spectral_fit.py` /
  `routes/eds_advanced.py` + frontend fit views.
- Item 3 (σ bands) should follow 2 — the residual/quality payload and
  the band payload want one serialisation convention.
- Item 7 (fit report CSV) consumes what 2 serialises; sequence after.
- Item 4 (vector chart export) is independent of all of the above.
- Item 6 (population histograms) is independent; its backend half is a
  new `calc/distributions.py`.
- Item 8 (batch/scripting reach) is a sweep item — do last, after the
  new verbs from 1/5/6 exist, so the sweep covers them too.

---

## Tier 1 — High Impact

1. **Voigt / Lorentzian / pseudo-Voigt in the spectral engine** (was
   audit R3) — Gaussian-only today (`calc/spectral_fit.py`); Voigt noted
   as a follow-up in `eds_peakfit.py`'s own header. `scipy.special.
   voigt_profile` costs nothing. Each shape needs its own analytic net
   area where `eds_peakfit` integrates `amp·σ·√(2π)`.

2. **Surface residuals + R² on existing fits** (was audit R4) —
   `FitResult.residual` and covariance are computed but never serialised
   or plotted; χ²ᵣ only. A residual trace under the fit and a quality
   readout in the fit summary, for `/eels/fit` and the EDS peak-fit path.

3. **Error bars / ±σ bands on existing analysis charts** (was audit R1)
   — uncertainty is computed everywhere and rendered only as
   `value ± err` text (`lib/formatUncertainty.ts`); no uPlot band/fill
   anywhere. Start with charts whose payload already carries σ.

4. **Vector (SVG) chart export + DPI control for analysis plots** (was
   audit R2) — charts export via `canvas.toBlob("image/png")` at screen
   resolution; the image stage already has a vector pipeline to reuse.

## Tier 2 — Medium Impact

5. **Savitzky–Golay smoothing + derivative for spectra/profiles** (was
   audit R5) — zero `savgol` hits in the tree; only a hardcoded box-3
   in `calc/eds.py`. Register as ops so batch/scripting get it free.

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

*(nothing yet)*
