# W3 imaging audit — map-to-scipy/scikit-image vs port-verbatim

Decision record for porting fermi-viewer's `+imaging/` package
(PORT_PLAN item 9). Every MATLAB implementation is **hand-rolled**
(toolbox-free), so "map" never means "same code upstream" — it means a
library equivalent exists whose numerics match exactly or within a
stated tolerance. Each row names its equivalence-test strategy against
the MATLAB goldens (`tests/golden/imaging.json`, captured on
closed-form deterministic synthetics so both languages regenerate the
inputs independently).

Legend — **map**: use scipy/skimage with parameter adaptation;
**port**: reimplement the MATLAB algorithm in numpy;
**hybrid**: library core + ported convention layer;
**done**: already shipped in `calc/`.

## Filters & intensity (→ `calc/filters.py`)

| MATLAB | Decision | Python | Parity notes / test strategy |
|---|---|---|---|
| `adjustContrast` | done | `render.window_level` | golden-tested |
| `applyGaussian` | **map** | `scipy.ndimage.gaussian_filter` | `mode='constant'` (conv2 'same' zero-pads), explicit `radius=ceil(3σ)` — scipy's default `int(3σ+0.5)` truncates differently for σ<1. 2-D kernel normalization factorizes, so separable = MATLAB's outer-product kernel. Exact (≤1e-12). |
| `applyMedian` | **map** | `scipy.ndimage.median_filter` | `mode='nearest'` = replicate padding. Order statistic → bit-exact. |
| `unsharpMask` | **port** (3 lines) | `filters.unsharp_mask` | skimage's version rescales/clips — ours must not. `img + amount·(img − blur)`. Exact. |
| `butterworthFilter` | **port** | `filters.butterworth` | Nonstandard normalization: D divided by max(D) so the far corner = 1 (skimage normalizes to Nyquist). DC bin of the high-pass forced to 1. Exact (FFT roundoff ~1e-12). |
| `clahe` | **port** | `filters.clahe` | skimage `equalize_adapthist` differs in clip-redistribution (iterative vs single uniform `excess/nBins` pass) and tile-edge handling (rounded-linspace edges, tile-center bilinear weights). Goldens would diverge — port verbatim. |
| `binImage` | **port** (trivial) | `filters.bin_image` | reshape-mean/sum over non-overlapping blocks, trim to divisible. Exact. |
| `areaDownsample` | **port** | `filters.area_downsample` | integer fast path = reshape-mean; general path = `ceil(idx/ratio)` bin assignment via bincount (≠ true area weights — intentional). Exact. |
| `generateThumbnail` | **port** (small) | `filters.thumbnail` | bilinear on `linspace(1,H,newH)` grid = align-corners sampling; skimage `resize` uses pixel-area convention → off by a fraction of a pixel. `map_coordinates(order=1)`. Exact. |
| `planeLevel` | **port** | `filters.plane_level` | poly design matrix (3/6/10 terms) + lstsq. Exact (≤1e-9; lstsq vs `\` can differ in degenerate fits). |
| `percentile` | **map** | `np.percentile` | identical linear-interpolation formula. Exact. |

## Segmentation & morphology (→ `calc/segment.py`)

| MATLAB | Decision | Python | Parity notes / test strategy |
|---|---|---|---|
| `bwlabel` / `connectedComponents` | **map** | `scipy.ndimage.label` | same partition; numbering both raster-first-encounter. Test: count + sorted areas exact. |
| `distanceTransform` | **port** | `segment.distance_transform` | chamfer 3-4 (÷3) is intentional (do-not-"fix"); scipy has only exact-EDT / taxicab / chessboard. Two-pass scan. Exact (integer chamfer). |
| `morphOp` | **map** | `scipy.ndimage.binary_*` | disk SE = L2 ≤ R (same as `skimage.morphology.disk`). Binary ops → bit-exact. |
| `multiOtsu` | **port** | `segment.multi_otsu` | skimage `threshold_multiotsu` differs in bin-edge→threshold mapping and has no 5-class coarse→fine scheme. Exhaustive search is simple — port for exact thresholds. |
| `watershed` | **port** (revised from hybrid) | `particles.watershed` | DT + grid-NMS markers + adoption flood all verbatim. The hybrid (skimage priority-flood on −D) was tried first and diverged badly — basin areas off by up to ~70 px on the golden synthetic — so the descending-D adoption flood (column-major tie order, highest-D-neighbour adoption, multi-pass) is ported exactly. Goldens: count, coverage and sorted areas all exact. Python-loop flood OK to ~1k²; compiled path if 4k becomes interactive. |
| `regionStats` | **map** | `skimage.measure.regionprops` (tranche 2) | area/centroid/bbox/equivalent_diameter/mean_intensity all standard; adapt 1-based centroid/bbox convention (+1) and add calibration + MinArea filter. Exact after convention shift. |
| `slic` | **map** | `skimage.segmentation.slic` (tranche 2) | MATLAB version is grayscale-intensity SLIC with m²=(C/S)²; skimage labels won't match — no goldens depend on per-pixel labels. Property tests only (segment count, connectivity, boundary recall on synthetic). |
| `particleAnalysis` | **port** (thin orchestration, tranche 2) | `segment.particle_analysis` | composes multi_otsu → watershed/label → region stats; logic-level port over the pieces above. |

## Texture, statistics, profiles (→ `calc/texture.py`, `calc/profiles.py`)

| MATLAB | Decision | Python | Parity notes / test strategy |
|---|---|---|---|
| `structureTensor` | **port** (small) | `texture.structure_tensor` (tranche 2) | np.gradient convention + Gaussian window (reuses filters.gaussian) + closed-form 2×2 eigs; skimage uses Sobel gradients by default → port for parity. Exact ≤1e-9. |
| `noiseEstimate` | **port** | `texture.noise_estimate` (tranche 2) | domain heuristics (MAD/0.6745/√20 Laplacian, 16×16 block-variance mode, Poisson-vs-Gaussian regression). Exact. |
| `radialProfile` | **port** | `profiles.radial_profile` (tranche 2) | (W+0.5, H+0.5) default center + floor-bin accumarray + NaN empty bins. Exact. |
| `azimuthalIntegrate` | **port** | `profiles.azimuthal_integrate` (tranche 2) | sector wrap-around (sMin ≥ sMax) + (W+1)/2 center convention. Exact. |
| `lineProfile` / `measureDistance` | done | `profiles.line_profile` / frontend `physDist` | tilt-corrected scalar distance available via the same correction factors |
| `fitInterfaceWidth` | **port** | `profiles.fit_interface_width` (tranche 2) | erf/sigmoid 4-param fit; mirror fminsearch with `scipy.optimize.minimize(method='Nelder-Mead')`. Tolerance: params ≤1e-6 (optimizer paths differ). |
| `templateMatch` | **hybrid** | `texture.template_match` (tranche 2) | NCC core maps to `skimage.feature.match_template` (same integral-image math); port the grid NMS + center-coordinate convention (template top-left + floor(size/2)). Peak positions exact, scores ≤1e-9. |
| `stitchImages` | **port** | `texture.stitch_images` (tranche 3) | strip FFT cross-correlation + peak-lag mapping + linear seam alpha-blend — domain-specific throughout. |

## Domain analysis (→ their own modules, tranche 3 / W4 items)

| MATLAB | Decision | Python | Notes |
|---|---|---|---|
| `computeFFT` | done | `fourier.compute_fft` | golden-tested |
| `geometricPhaseAnalysis` | **port** | `calc/gpa.py` | centerpiece; Butterworth g-mask + phase-ramp shift + 2×1D unwrap + G⁻¹ solve. Goldens on synthetic strained lattice. |
| `latticeMeasure` | **port** | `calc/diffraction.py` | pinned conventions (floor(size/2)+1 FFT center; 0.5 px offset is a do-not-"fix") |
| `countDefectLines` | **port** | `calc/defects.py` | oriented-derivative kernels + Otsu + Ham's intercept method |
| `surfaceRoughness` | **port** | `calc/roughness.py` | ISO Ra/Rq/Rz/Rsk/Rku + triangulated SAR + bearing ratio; reuses plane_level |
| `fitGaussian2D` (+atoms) | **port** | `calc/atoms.py` (W4 #15) | hand-rolled LM with ridge regularization; mirror with `scipy.optimize.least_squares`, params ≤1e-6 |
| `kmeansLite` (+ml) | **port** | `calc/ml.py` (W4 #15) | seeded k-means++ reproducibility matters; no sklearn dep. RNG sequences differ MATLAB↔numpy → goldens on final inertia/centers for fixed synthetic, tolerance 1e-9 with same seeding only if RNG ported; otherwise property tests. |
| `addColorbar` / `addScaleBar` / `buildFigurePanel` | **port** | export pipeline (W5 #20) | rendering/composition; goldens = PNG checksums |
| `getGrayscale` / `getStageTilt` | **port** (trivial) | `io/` helpers | BT.601 luma; FEI radians-vs-degrees heuristic |

## Golden capture strategy

Inputs are **closed-form synthetics** (no RNG) defined identically in
`tools/matlab/freeze_reference_values.m` and `tests/test_imaging.py`:

```
base(r, c) = sin(r/7)·cos(c/11) + 0.001·r·c/(64·96)      on 64×96, r,c 1-based
noisy      = base + 0.05·sin(13·r + 7·c)                  (deterministic "noise")
bw         = base > 0.2                                   (binary fixture)
```

sin/cos agree across IEEE implementations to ~1e-15; goldens are
compared at rel 1e-9 except where a row above states otherwise.
Captured values are scalar fingerprints (sums, |sums|, specific pixels,
thresholds, counts, sorted areas) — small JSON, not arrays.

## Tranche order

1. **Tranche 1 (this branch):** filters.py + segment.py basics — the
   `/filter` endpoint's menu (gaussian, median, unsharp, butterworth,
   clahe, bin, downsample, thumbnail, plane-level) + multi_otsu, label,
   morphology, distance transform.
2. **Tranche 2:** watershed, region stats, particle analysis, structure
   tensor, noise estimate, radial/azimuthal, interface width, template
   match, SLIC.
3. **Tranche 3:** GPA, defect counting, roughness, stitching, lattice
   measure (with W4 scraps: CTF, back-projection, VDF, composition
   profile).
