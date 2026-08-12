# OriginPro / JMP gap audit — 2026-07-28 (scope reduced 2026-07-28)

**Scope decision (user, 2026-07-28): FermiViewer stays image-focused.**
Replacing OriginPro/JMP as general graphing/statistics tools is *not*
this repo's mission — that job belongs to a different tool. This audit
was originally written against the broader goal; it is now trimmed to
the subset of gaps that make FermiViewer better at **presenting and
quantifying its own image-derived results** (spectra, profiles, fits,
particle/grain/measurement populations). Everything that would require
FermiViewer to accept arbitrary external data, grow a worksheet, or
host a generic fit/plot workshop is **DECLINED** below, in the
`feature_triage.md` sense.

Method: three full-codebase sweeps (plotting/export, fitting/numerics,
data/statistics/batch) of v0.1.22 @ `dece9e6`, with file-level
evidence. Companion docs: `parity_report.md`, `feature_triage.md`.

The guiding rule used for each triage call:

> If the data originates from an image or spectrum FermiViewer opened,
> polishing its analysis and presentation is in scope. If the workflow
> starts from a column of numbers produced elsewhere, it is out.

---

## 0 · Where FermiViewer already beats Origin/JMP (no gap)

The reasons the image workflow consolidates here, none of which exist
in Origin or JMP:

- **Physics-correct spectral quantification.** Hydrogenic EELS edge
  shapes, Fano-constrained EDS linewidths, Kramers continuum,
  Cliff–Lorimer / ZAF / ζ-factor with Poisson + delta-method error
  propagation to ±1σ on every at%/wt% (`calc/uncertainty.py`,
  `calc/spectral_fit.py`, `calc/eds_peakfit.py`).
- **Per-pixel spectrum-image map fitting** (`calc/eels_model.py:218`).
- **Publication-grade *image* export**: PNG/JPEG/TIFF-16/SVG/PDF,
  72–1200 dpi, journal width presets, vector scale bar / colorbar /
  measurements / caption band (`routes/export.py`, `_export_svg.py`).
- **Provenance → methods paragraph** (`ops/provenance.py`), session
  files with full-dtype pixel sidecars (`io/session_file.py`).
- **Native EM format IO** — the data never has to leave.
- Batch recipes as bounded server jobs with portable `.fvbatch.json`
  presets (`routes/batch_ops.py`).

## 1 · Triage — BUILD (image-focused gaps)

These close real weaknesses in how FermiViewer's *own* results are
fitted, displayed, and exported. No new runtime dependencies — every
item rides on scipy/uPlot infrastructure already in the tree.

| Pick | ID | Gap | Today (evidence) | Why in scope |
|---|---|---|---|---|
| ✔ | R1 | **Error bars / ±σ bands on existing analysis charts** | Uncertainty is computed but rendered only as `value ± err` text (`lib/formatUncertainty.ts`); no uPlot band/fill anywhere | The app computes rigorous 1σ everywhere and then hides it from every plot — quant results should *show* their error bars |
| ✔ | R2 | **Vector (SVG) chart export + DPI control for analysis plots** | Charts export via `canvas.toBlob("image/png")` at screen resolution (`PlotContextSurface.tsx:29`); the image stage already has a vector pipeline | Spectra/profile figures are publication output exactly like images; reuse `_export_svg.py` dpi/width plumbing |
| ✔ | R3 | **Voigt / Lorentzian / pseudo-Voigt in the spectral engine** | Gaussian-only peaks (`calc/spectral_fit.py:280`); Voigt already noted as a follow-up in `eds_peakfit.py:16` | Physics of the existing EDS/EELS/ELNES fits, not a generic model library; `scipy.special.voigt_profile` costs nothing |
| ✔ | R4 | **Surface residuals + R² on existing fits** | `FitResult.residual` and covariance computed but never serialised or plotted; χ²ᵣ only | Judging an EELS/EDS/interface fit needs a residual trace; the data is already in `FitResult` |
| ✔ | R5 | **Savitzky–Golay smoothing + derivative for spectra/profiles** | Zero `savgol` hits; no smoothing exposed on any spectrum (only a hardcoded box-3 in `eds.py:375`) | Standard pre-treatment of data the app itself produced; register as ops so batch/scripting get it free |
| ✔ | R6 | **Population histograms + distribution fitting for measured objects** | Particle/grain/distance stats export as raw rows; only image-intensity histograms exist; no median/quartiles reported (`lib/measureStats.ts`) | Particle-size / grain-size distributions (normal / log-normal / Weibull via `scipy.stats.*.fit`) are the canonical image-derived statistic — this is the one JMP-shaped feature that is squarely in-mission |
| ✔ | R7 | **Batch + scripting reach for existing analyses** | Op catalogue = 17 ops, no spectral fitting (`ops/catalogue.py`); `fermiviewer.api` reaches ~17 of ~105 server capabilities | Not new capability — making what already exists automatable; EDS per-pixel peak-fit maps fall out of the same registration |
| ✔ | R8 | **Fit-report export (params ± σ + stats to CSV)** | CSV exists for quant tables only | Completes the provenance story for fits the app already runs |

Suggested order: R3/R4 (engine), R1/R2 (presentation), R5, R6, R8, R7.

### Optional (Tier 2, only if the need actually recurs)

| Pick | ID | Gap | Note |
|---|---|---|---|
| ? | R9 | Two-sample comparison of measured populations (t-test / Mann–Whitney on grain/particle stats) | "Did sample A's grain size differ from B's?" is image-derived, but borderline — build only if R6 gets real use |
| ? | R10 | Headless folder batch (`fv run recipe.json` over paths) | Folder-watch half already noted unimplemented in `ops/batch.py:9`; image-focused but not urgent |
| ? | R11 | Baseline options for spectra (SNIP / anchor spline) | Only if the joint-fit backgrounds prove insufficient for real ELNES work |
| ? | R12 | Chart dark-mode theming (`.u-*` CSS overrides) | Cosmetic; stock uPlot chrome ignores the app theme |

## 2 · Triage — DECLINED (general-purpose tool territory)

Everything below was in the original audit and is now explicitly out:
it serves the "replace OriginPro/JMP wholesale" goal, which this repo
no longer carries. External data goes to the graphing tool of choice;
FermiViewer's CSV exports (17 sites, provenance headers) are the
hand-off interface.

| Pick | ID | Feature | Reason |
|---|---|---|---|
| ✘ | X1 | CSV/TXT/Excel numeric **import**, worksheet UI, formula columns, sort/filter/edit | The moment arbitrary columns come in, this is a data-analysis app. Consistent with the A10 precedent ("CSV export suffices", `feature_triage.md`) |
| ✘ | X2 | Generic "plot any XY data" workshop; user-configurable plot styling (fonts, colors, ranges, legends, templates) | Analysis charts are result views, not a graphing canvas; fixed sane styling stays |
| ✘ | X3 | Generic "fit any XY data" workshop, user-defined model equations, parameter-tie expressions, global multi-dataset fit | Fitting stays physics-scoped (EELS/EDS/interface/CTF/roughness); no expression engine |
| ✘ | X4 | Chart-type expansion: bar, box, violin, waterfall, contour, polar, ternary, dual y-axes, insets, multi-panel chart builder | General graphing; the montage/figure-panel path covers image composition already |
| ✘ | X5 | Hypothesis-testing suite (ANOVA + post-hoc, normality, nonparametrics beyond R9), regression-with-inference, table-level PCA/clustering | JMP's job |
| ✘ | X6 | DOE, SPC/control charts, gauge R&R, reliability, mixed models, PLS | Was already recommended DECLINE in the original audit |
| ✘ | X7 | Spline/LOESS toolboxes, 1D IIR/Wiener/wavelets, ODR, robust-loss options | Signal-processing generality with no image-workflow driver |
| ✘ | X8 | Multi-page PDF/HTML report generator, report templates | Image/figure export + JSON/CSV with provenance suffices |

## 3 · Verdict under the reduced scope

FermiViewer's job is to be the best place to *do* the microscopy
analysis and to hand off publication-ready figures and clean,
provenance-stamped CSVs. The R-items close the genuine embarrassments
within that mission — computed error bars that no plot shows, fits with
no residuals, raster-only chart export next to a vector image pipeline,
Gaussian-only peaks, and particle/grain populations that leave the app
as raw rows. General graphing and statistics remain the job of a
dedicated tool, fed by FermiViewer's CSV exports.
