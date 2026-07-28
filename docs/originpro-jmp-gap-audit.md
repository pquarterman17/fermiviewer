# OriginPro / JMP gap audit — 2026-07-28

Goal: make FermiViewer the daily workhorse and retire OriginPro and JMP
from the EM/materials workflow. This audit inventories what those two
packages provide that FermiViewer (v0.1.22 @ `dece9e6`) does not, grades
each gap for an electron-microscopy workflow, and proposes a build order.
Method: three full-codebase sweeps (plotting/export, fitting/numerics,
data/statistics/batch) with file-level evidence, compared against
OriginPro's graphing + Peak Analyzer / NLFit toolset and JMP's
statistical-discovery toolset. Companion docs: `parity_report.md`,
`feature_triage.md`.

Severity legend — how much it blocks "replace Origin/JMP tomorrow":
**HIGH** = used weekly in a typical EM workflow, no workaround inside
FermiViewer; **MED** = used regularly, awkward workaround exists;
**LOW** = occasional use or exotic.

---

## 0 · Where FermiViewer already beats Origin/JMP (no gap)

These are the reasons to consolidate *into* FermiViewer, and none of
them exist in Origin or JMP:

- **Physics-correct spectral quantification.** Hydrogenic EELS edge
  shapes, Fano-constrained EDS linewidths, Kramers continuum,
  Cliff–Lorimer / ZAF / ζ-factor with Poisson + delta-method error
  propagation to ±1σ on every at%/wt% (`calc/uncertainty.py`,
  `calc/spectral_fit.py`, `calc/eds_peakfit.py`). Origin cannot do this
  at all; doing it in JMP would mean rebuilding the physics by hand.
- **Per-pixel spectrum-image map fitting** with a linearised
  fixed-exponent trick (`calc/eels_model.py:218`).
- **Publication-grade *image* export**: PNG/JPEG/TIFF-16/SVG/PDF,
  72–1200 dpi, journal width presets (Nature 89/183 mm, Science 85 mm,
  ACS 84 mm), vector scale bar / colorbar / measurements / caption band
  in SVG (`routes/export.py`, `_export_svg.py`, `ExportDialog.tsx`).
- **Provenance → methods paragraph** (`ops/provenance.py`,
  `Image.methods()`), session files with full-dtype pixel sidecars
  (`io/session_file.py`), named workspaces.
- **Native EM format IO** (DM3/4, EMD, BCF, SER, MRC, HDF5 family, MSA,
  Nanoscope AFM) — the whole reason the data never has to leave.
- Batch recipes as bounded server jobs with portable `.fvbatch.json`
  presets (`routes/batch_ops.py`, `lib/batchRecipePresets.ts`).

## 1 · The shape of the gap

The three sweeps converge on one diagnosis: **FermiViewer is an
analysis-result viewer, not yet a general graphing or statistics tool.**
Three structural holes produce almost every line item below:

1. **No generic data path in.** The loader registry accepts only
   binary EM formats plus `.msa`/`.cif` (`io/registry.py`). There is no
   CSV/TXT/Excel import, no worksheet object, no way to hand FermiViewer
   a column of numbers. Everything Origin/JMP-shaped starts here.
2. **Charts are fixed-purpose and non-configurable.** ~13 hard-coded
   uPlot line charts; axis titles/fonts/colors/ranges/legends all
   compile-time; PNG-only export at screen resolution; no error bars,
   no dual axes, no templates (`frontend/src/components/workshops/*`,
   `plots/PlotContextSurface.tsx`).
3. **Statistics stop at mean/std.** No `scipy.stats` import anywhere;
   no p-value is computed anywhere in the codebase; no distribution
   fitting, no hypothesis tests, no population histograms.

The good news: the hard parts of closing these already exist. The
fitting engine (`calc/spectral_fit.py`) is a competent bounded NLLS
core with covariance and weights; the chart context-menu/export scaffold
(`PlotContextSurface`) wraps every plot; the CSV layer has provenance
headers; scipy is already a dependency (`scipy.stats` costs nothing).
Most Tier-1 items below are wiring, not research.

---

## 2 · Gaps vs OriginPro

### 2.1 Graphing (G1–G12)

| ID | Gap | FermiViewer today (evidence) | Severity |
|---|---|---|---|
| G1 | Plot arbitrary data (import CSV → plot columns) | No CSV import; every plot bound to an analysis result type | **HIGH** |
| G2 | Error bars / ±σ bands on charts | Uncertainty computed but rendered only as `value ± err` text (`lib/formatUncertainty.ts`); no uPlot band/fill anywhere | **HIGH** |
| G3 | Vector chart export (SVG/PDF/EPS) + DPI control | Charts export via `canvas.toBlob("image/png")` at screen resolution only (`PlotContextSurface.tsx:29`); image-stage export is vector-capable but charts are not | **HIGH** |
| G4 | User-editable plot styling: axis titles, fonts, series colors, line styles, ranges, tick control, legend position | All hard-coded; only 3/13 plots have any axis label; ticks/fonts/colors are literals in source | **HIGH** |
| G5 | True log axes | 1 plot (PSD, `distr: 3`); EDS "Log counts" is a data transform on a linear axis (`EdsSpectrumPlot.tsx:55`) | MED |
| G6 | Multi-panel *chart* figures, linked axes, panel letters | Exists for images (`/api/export/figure`) but no chart composition, no `uPlot.sync`, no insets | MED |
| G7 | Plot templates / saved styles (`.otp` equivalent) | None; only export prefs persist (`lib/prefs.ts`) | MED |
| G8 | Chart types: bar, box, violin, waterfall/stacked, contour, polar, ternary | Only line, one scatter (Noise), one histogram (display-only), one 3D surface | MED (box/histogram MED, rest LOW) |
| G9 | Dual / secondary y-axes | Every plot has exactly one y scale | MED |
| G10 | User annotations on charts (text, arrows, callouts) | Annotation suite exists but only on the image stage (`Stage/MeasureOverlay.tsx`) | LOW |
| G11 | Fill-under-curve, step/spline paths, stem plots | `paths:`/`fill:` never set on any series | LOW |
| G12 | Chart theming follows app dark mode | Stock uPlot CSS imported once, zero `.u-*` overrides | LOW |

### 2.2 Fitting & peak analysis (F1–F10)

| ID | Gap | FermiViewer today (evidence) | Severity |
|---|---|---|---|
| F1 | General "fit any XY data" workshop (model picker, parameter table, vary/fix, iterate) | None; fitting reachable only through domain routes keyed to a session image (`routes/spectral_fit.py`, `routes/eds_advanced.py`) | **HIGH** |
| F2 | Peak-shape library: Lorentzian, Voigt, pseudo-Voigt, Pearson VII, asymmetric | Gaussian, power-law, linear/poly background, Kramers, hydrogenic edges only (`calc/spectral_fit.py:280-355`); Voigt noted as follow-up in `eds_peakfit.py:16` | **HIGH** |
| F3 | Free multi-peak fitting driven by auto peak detection (positions + widths free) | EDS/EELS fits fix centers to known lines and σ to the Fano model; only amplitudes free (`eds_peakfit.py:44`) — correct for quant, useless for generic spectra | **HIGH** |
| F4 | Fit statistics: R²/adj-R², residual plots, confidence/prediction bands, correlation matrix, AIC/BIC | Reduced χ² + 1σ errors only; residual array and covariance computed but never serialised or plotted | **HIGH** |
| F5 | Baseline toolbox: anchor points, ALS/airPLS, SNIP, rolling ball, spline | Joint-fit backgrounds (linear/bremsstrahlung/power-law) only; nothing interactive or pre-subtractive beyond EELS pre-edge windows | MED |
| F6 | User-defined model functions (equation editor) | No expression engine (`sympy`/`asteval`/`numexpr` absent); new models require editing source | MED |
| F7 | Parameter fixing/sharing/ties (`amp2 = 0.5·amp1`), global multi-dataset fit | Box bounds only (`Component.lower/upper`); no `vary=False`, no expressions | MED |
| F8 | User-supplied initial guesses / interactive seeding | All seeds automatic and non-overridable | MED |
| F9 | Fit report export (params + errors + stats to CSV/text) | CSV exists for quant tables only, not fit results | MED |
| F10 | Robust loss (soft-L1/Huber), ODR errors-in-x | `least_squares(method="trf")` with default loss only (`spectral_fit.py:220`) | LOW |

### 2.3 Worksheets & data handling (D1–D4)

| ID | Gap | FermiViewer today (evidence) | Severity |
|---|---|---|---|
| D1 | CSV/TXT numeric import | Loader registry is binary-EM-only (`io/registry.py`) | **HIGH** |
| D2 | Persistent worksheet: sort, filter, formula columns, units, plot-from-table | One transient `ResultsWindow` table, 100-row pages, CSV/JSON download only | **HIGH** |
| D3 | Copy table to clipboard | Clipboard is images/plots only | MED |
| D4 | Excel read/write | Zero references repo-wide | LOW (CSV suffices; consistent with A10 in `feature_triage.md`) |

### 2.4 Signal processing (S1–S4)

| ID | Gap | FermiViewer today (evidence) | Severity |
|---|---|---|---|
| S1 | Savitzky–Golay smoothing + SG derivatives | Zero hits for `savgol`; no smoothing exposed on spectra at all (only a hardcoded box-3 inside peak detect, `eds.py:375`) | **HIGH** |
| S2 | Numerical differentiate/integrate an arbitrary curve (with baseline choice) | Internal-only (`np.gradient`/`np.trapezoid` inside quant code) | MED |
| S3 | Spline/LOESS smoothing & interpolation | `UnivariateSpline`/`splrep`/LOWESS absent | LOW |
| S4 | 1D IIR filters, Wiener, wavelets, Hilbert envelope | Absent (the "butterworth" op is a 2D FFT mask) | LOW |

### 2.5 Automation (B1–B4)

| ID | Gap | FermiViewer today (evidence) | Severity |
|---|---|---|---|
| B1 | Fitting inside batch recipes | Op catalogue = 17 ops, none spectral (`ops/catalogue.py`); no EDS per-pixel peak-fit maps | **HIGH** |
| B2 | Scripting API covers analysis | `fermiviewer.api` reaches 17 of ~105 server capabilities; EELS/EDS/diffraction scripting requires private `calc/` imports | **HIGH** |
| B3 | Headless folder batch (`fv run recipe.json --input *.dm4`) | CLI only starts a server/window; batch takes session `image_ids`, not paths; folder-watch noted but unimplemented (`ops/batch.py:9`) | MED |
| B4 | Macro robustness (multiple named macros, export/import, value ops) | Single unnamed localStorage slot, image ops only (`lib/macro.ts`) | LOW |

---

## 3 · Gaps vs JMP (J1–J10)

For an EM/materials user, JMP's daily value is population statistics on
measured objects (particles, grains, distances, layer widths) and quick
exploratory graphics — not its full DOE/quality stack.

| ID | Gap | FermiViewer today (evidence) | Severity |
|---|---|---|---|
| J1 | Histograms of measurement populations (particle diameters, grain areas, distances) | Only image-intensity histograms; ROI histogram is emitted as a table (`MeasurePanel.tsx:150`) | **HIGH** |
| J2 | Distribution fitting (normal / **log-normal** / Weibull) with parameters + CI — the particle/grain-size-distribution workflow | None anywhere | **HIGH** |
| J3 | Descriptive stats beyond mean/std/min/max: median, quartiles, IQR, CI of the mean | Median/percentiles used internally, never reported (`lib/measureStats.ts` is N/mean/pop-σ/min/max) | **HIGH** |
| J4 | Hypothesis tests: t-test, one-way ANOVA + Tukey, nonparametrics (Mann–Whitney), normality tests | No `scipy.stats` import; no p-value computed anywhere in the codebase | MED-HIGH (two-sample t and one-way ANOVA are the workhorses: "did sample A's grain size differ from B's?") |
| J5 | Box plots / grouped comparisons across samples | No box/violin chart type | MED |
| J6 | Linear regression with inference (slope CI, p, R², residual diagnostics) | One OLS with R² (noise var-vs-mean, `calc/texture.py`), not general-purpose | MED |
| J7 | PCA / clustering on arbitrary tables | SVD is spectrum-image-only; k-means/softmax are pixel-feature-only (`calc/ml.py`) | LOW-MED |
| J8 | DOE (design + analysis) | None | LOW — keep JMP (see §4) |
| J9 | SPC control charts, capability, gauge R&R | None | LOW — keep JMP |
| J10 | Reliability/survival, mixed models, PLS | None | LOW — keep JMP |

---

## 4 · Deliberately out of scope — keep JMP for these

Recommend **DECLINE** (in the `feature_triage.md` sense) rather than
chase full JMP parity:

- **DOE** (J8): custom/optimal design generation is a deep, mature
  specialty; an EM viewer gains nothing from a worse version of it.
- **SPC / quality / gauge R&R** (J9), **reliability, mixed models, PLS**
  (J10): same reasoning. If these are used at all, they are used rarely
  enough that keeping a JMP license (or using Python/statsmodels ad hoc)
  beats rebuilding them.
- **Excel IO** (D4): CSV round-trip suffices, consistent with the A10
  precedent.

If J8–J10 are *not* actually in current use, JMP can be dropped as soon
as Tier 1 below ships, since J1–J4 cover the microscopy-relevant slice.

## 5 · Suggested build order

### Tier 1 — retires OriginPro for daily EM work (and most of JMP)

Ordered so each item unlocks the next; every one leans on existing
infrastructure rather than new dependencies.

1. **CSV/TXT import → generic XY dataset** (D1, feeds G1/F1). New
   `DataKind` or lightweight table object; loader is ~a day next to the
   existing `.msa` text parser.
2. **Generic Plot workshop** (G1, G4 partial, G5, G2): plot any XY
   dataset or any exported-result table; per-series color/style/label,
   axis titles/ranges, log toggles, error-bar series fed by existing ±σ
   columns. One new uPlot wrapper, reusing `PlotContextSurface`.
3. **Vector chart export** (G3): render the active uPlot config to SVG
   server-side or via a canvas→SVG pass; reuse the image pipeline's
   dpi/width plumbing. Publication figures are the single most common
   reason to bounce out to Origin.
4. **General Fit workshop** (F1–F4, F8, F9): expose
   `calc/spectral_fit.py` on arbitrary XY data; add Lorentzian, Voigt
   (`scipy.special.voigt_profile` — zero new deps), pseudo-Voigt,
   exponential decay, sigmoid; free multi-peak mode seeded by
   `scipy.signal.find_peaks`; serialise `FitResult.residual` +
   covariance; residual subplot + R²; fit-report CSV. The engine,
   bounds, weights, and covariance code all already exist — this is
   mostly routing + UI.
5. **Savitzky–Golay + derivative/integrate ops** (S1, S2):
   `scipy.signal.savgol_filter`, registered in the op catalogue so
   batch and scripting get them for free.
6. **Population statistics + distribution fitting** (J1–J3): histogram
   chart of any results-table column; report median/quartiles/CI;
   normal/log-normal/Weibull fits via `scipy.stats.*.fit` with the fit
   overlaid. Rides on items 1–2.
7. **Batch + scripting reach** (B1, B2): register spectral-fit and
   quant ops in the catalogue so recipes and `fermiviewer.api` cover
   them; EDS per-pixel peak-fit maps fall out of the same registration.

### Tier 2 — quality of life / full Origin comfort

- t-test + one-way ANOVA + Mann–Whitney with p-values (J4), box plots
  (J5) — `scipy.stats` only.
- Baseline toolbox: anchor-point spline + ALS + SNIP (F5).
- Parameter fix/tie expressions and shared-parameter global fit (F7);
  user-defined models via a safe expression evaluator (F6).
- Plot templates/saved styles (G7); dual y-axes (G9); multi-panel chart
  builder with linked x-axes via `uPlot.sync` (G6).
- Worksheet upgrades: sort/filter/formula column, copy-to-clipboard
  (D2, D3).
- Headless batch CLI over folders (B3).
- General linear regression with inference (J6).

### Tier 3 — nice-to-have / probably never

- Contour/polar/ternary/waterfall charts (G8 tail), ODR/robust loss
  (F10), wavelets (S4), chart annotations (G10), table-level PCA (J7).
- Everything in §4 stays declined.

## 6 · Verdict

- **Today**: FermiViewer already replaces Origin/JMP for everything
  *upstream* of the figure — quant, maps, measurements, image-figure
  export — and its uncertainty handling is better than either. It cannot
  yet replace them for generic plotting, generic curve fitting, or any
  population statistics; those workflows currently exit via CSV.
- **After Tier 1** (~7 work items, no new runtime dependencies beyond
  what scipy already provides): OriginPro becomes unnecessary for the
  weekly EM workflow, and JMP becomes unnecessary unless DOE/SPC are in
  active use.
- **After Tier 2**: Origin fully retired; JMP retained only as a
  DOE/SPC specialty tool, or dropped if those are unused.
