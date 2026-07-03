# Interface-roughness metrology from TEM cross-sections

This document derives the statistics behind fermiviewer's per-column
interface-roughness measure $\sigma_w$ and its companions ($\sigma_{\mathrm{chem}}$,
$\xi$, $H$, conformality $r$). The pipeline lives in
`calc/trace_roughness.py`; `calc/layers.py` orchestrates it
(laterally-averaged depth profile $\to$ erf fits $\to$ per-column trace
$h(x)$). The target reader knows XRR roughness: the running theme is that a
cross-section image and a reflectometry curve measure *the same* interface
width, decomposed the *same* way, with the *same* chemical-vs-geometric
ambiguity — but the image resolves it laterally, one column at a time.

Everything is computed in pixels and multiplied by `pixel_size` on the way
out. Below, $\Delta x$ is the pixel size, $L = N\,\Delta x$ the lateral
field of view (FOV), and $h(x_j)$ the sub-pixel depth of one interface at
lateral column $x_j$, $j = 1 \dots N$.

---

## 1. Why full-FOV tracing, not point-to-point

The traditional cross-section roughness number is a caliper: an operator
places two markers on the peaks and valleys of an interface and reports the
peak-to-valley excursion, or drops a handful of point measurements and takes
their spread. Both are statistically hopeless:

- **No error bar.** A peak-to-valley from $n \approx 2$–$5$ hand-picked
  points has an enormous, unquantified sampling variance. Peak-to-valley in
  particular is an *extreme-value* statistic — it grows without bound as more
  points are sampled and cannot be compared between images taken at different
  magnifications.
- **Selection bias.** An operator's eye is drawn to the largest excursions,
  biasing the estimate high.
- **Wrong estimand.** XRR, AFM, and diffuse-scattering theory all speak in
  terms of the *rms* height deviation $\sigma$, not peak-to-valley. Mixing
  conventions makes the cross-section number incomparable with the technique
  the reader actually wants to cross-check.

Tracing the interface across *every* lateral column turns the measurement
into a proper sample. From $N \sim 10^3$ correlated samples of $h(x)$ we get
an rms estimate

$$\sigma_{\mathrm{rms}}^2 \;=\; \frac{1}{N}\sum_{j=1}^{N}\big(h(x_j)-\bar h\big)^2,$$

a spatial spectrum, a correlation length, and — crucially — a
*confidence interval* (Section 9). The per-column edge is found cheaply by a
3-point parabolic fit to the gradient magnitude (`_parabolic_edge`), which is
sub-pixel and fast enough to run on all $N$ columns; the expensive erf fit is
reserved for the laterally-averaged profile (Section 6).

---

## 2. Form, waviness, roughness — and measurement bandwidth

Surface metrology (ISO 4287; Whitehouse) partitions a measured profile into
three wavelength bands:

- **Form** — the longest wavelengths: overall tilt and bow. In a
  cross-section these are *instrumental*, not physical: a $0.5^{\circ}$
  residual sample tilt over a $1024$ px field injects a linear ramp of
  $1024\tan(0.5^{\circ}) \approx 9$ px peak-to-peak, which a naive
  `np.std(trace)` reports as $\sim 2.6$ px of "roughness" that is entirely
  an artifact. Substrate bow adds a quadratic term.
- **Waviness** — the mid band: the actual meso-scale undulation of the
  interface.
- **Roughness** — the shortest wavelengths, down to the resolution limit.

`clean_trace` removes form by fitting and subtracting a degree-$p$
polynomial ($p=2$ by default: tilt + bow),

$$\hat h(x) = \sum_{k=0}^{p} a_k x^k, \qquad
  \delta(x) = h(x) - \hat h(x),$$

and reports statistics on the residual $\delta(x)$. This is a **high-pass
filter**. Its passband sets the measurement bandwidth, and $\sigma_w$ is
therefore a *bandpass* quantity, not an absolute one:

$$\lambda_{\text{low-freq cut}} \;\sim\; \frac{L}{p+1}
   \qquad\text{(set by the detrend order)},$$
$$\lambda_{\text{high-freq cut}} \;\sim\; \max\!\big(2\,\Delta x,\; w_{\mathrm{PSF}},\; t\big)
   \qquad\text{(pixel/probe/foil, Section 8).}$$

The consequence a reflectometry practitioner must internalize: **roughness
at lateral wavelengths comparable to the FOV is deliberately discarded as
form.** If the true interface has a long, gentle undulation with
$\lambda \gtrsim L$, the polynomial swallows it and $\sigma_w$ is blind to
it. This is a feature — it is the only way to reject tilt — but it means two
measurements are only comparable when they share a FOV and detrend order.
Report both. (XRR has the mirror-image bandwidth: specular reflectivity is
sensitive to roughness over the coherence length of the beam, typically
microns, so XRR and cross-section $\sigma$ agree only where their bands
overlap.)

The one-sided, Hann-windowed PSD (`trace_psd`) makes the bandwidth explicit:
it plots power against lateral wavelength so the user can see which band
dominates and where the noise floor takes over. It is Parseval-normalized so
that $\sum_k P_k \approx \operatorname{Var}[\delta]$.

---

## 3. Robust estimation: MAD, kappa-sigma, quality flag

A cross-section trace is contaminated by non-Gaussian outliers: hot pixels,
Pt/C contamination beads, FIB curtain residue, and columns where the edge
detector locked onto the wrong feature. An ordinary standard deviation has a
breakdown point of $0\%$ — one wild column inflates it without limit.
`robust_sigma` uses the **median absolute deviation** (breakdown point
$50\%$):

$$\hat\sigma = 1.4826 \cdot \operatorname{median}_j\big|\,\delta(x_j) - \operatorname{median}_k \delta(x_k)\,\big|.$$

The constant $1.4826 = 1/\Phi^{-1}(0.75) = 1/0.6745$ rescales the MAD so that
$\hat\sigma$ is a *consistent* estimator of the standard deviation for
Gaussian data (the MAD of $\mathcal N(0,\sigma^2)$ equals $0.6745\,\sigma$).

On top of the robust scale, `clean_trace` runs **iterative $\kappa$-sigma
rejection**: fit the polynomial, compute the robust $\hat\sigma$ of the
residuals, drop columns with $|\delta(x_j)| > \kappa\hat\sigma$ ($\kappa = 4$
default), and refit. Refitting matters — a gross outlier biases the very
trend it is judged against, so it must be excluded and the form re-estimated
(up to `n_iter = 3` passes, or until the keep-set stabilizes).

The surviving fraction is returned as a **quality flag**:

$$q = \frac{\#\{\text{columns kept}\}}{\#\{\text{finite columns}\}} \in [0,1].$$

$q$ close to $1$ means the trace was clean; a low $q$ (say $< 0.8$) warns that
many columns were rejected and the number should be treated with suspicion
(heavy curtaining, a mistraced interface, or a genuinely discontinuous
interface that the polynomial-plus-Gaussian model does not describe).

---

## 4. Noise-floor subtraction

The robust residual rms still contains two contributions in quadrature: real
lateral roughness, and **edge-localization jitter** — the per-column error of
the parabolic edge estimator, driven by shot noise. These separate by their
*correlation structure*:

- Real roughness is laterally **correlated** — the probe/PSF already smooths
  the image over a few pixels, so neighboring columns see nearly the same
  interface height.
- Localization jitter is column-to-column **independent** (white).

The lag-1 structure function isolates the white part. For the first
difference $d_j = \delta(x_{j+1}) - \delta(x_j)$, a correlated signal nearly
cancels (adjacent heights are almost equal), while independent jitter of
variance $\sigma_{\mathrm{loc}}^2$ contributes

$$\big\langle d_j^2 \big\rangle = 2\,\sigma_{\mathrm{loc}}^2.$$

Rather than a mean (which the same outliers of Section 3 would spoil),
`_noise_floor` uses the **median** of $d_j^2$, robustified by the
normal-consistency factor for a squared Gaussian. If $d_j \sim \mathcal
N(0,\,2\sigma_{\mathrm{loc}}^2)$ then $d_j^2/(2\sigma_{\mathrm{loc}}^2) \sim
\chi^2_1$, and the median of a $\chi^2_1$ variate is

$$\operatorname{median}(\chi^2_1) = \big[\Phi^{-1}(0.75)\big]^2 = 0.6745^2 = 0.4549.$$

Hence

$$\sigma_{\mathrm{loc}}^2 \;=\; \frac{\operatorname{median}_j\!\big(d_j^2\big)}{2\cdot 0.4549}.$$

The waviness is then the noise-corrected rms:

$$\boxed{\;\sigma_w^2 \;=\; \sigma_{\mathrm{robust}}^2 \;-\; \sigma_{\mathrm{loc}}^2\;}$$

clamped at zero (`_noise_corrected`). This is exactly the deconvolution a
reflectometrist does when subtracting the instrumental resolution in
quadrature: $\sigma_{\mathrm{loc}}$ is the "resolution" of the trace, and
$\sigma_w$ is what is left after removing it. When
$\sigma_{\mathrm{loc}} \gtrsim \sigma_{\mathrm{robust}}$ the interface is
smoother than the measurement can resolve and $\sigma_w \to 0$: honest, but a
signal to acquire at higher dose or magnification.

---

## 5. Self-affine height-height correlation

Beyond the single number $\sigma_w$, the *shape* of the roughness is
characterized by the height-height correlation function (HHCF)

$$g(r) = \big\langle\, [\,h(x+r) - h(x)\,]^2 \,\big\rangle$$

(`hhcf`, averaged over all valid column pairs at lag $r$). Growth-front and
self-affine surfaces (Sinha, Sirota, Garoff & Stanley 1988) follow

$$g(r) = 2\sigma^2\Big[\,1 - \exp\!\big(-(r/\xi)^{2H}\big)\,\Big],$$

with two physical parameters:

- **Correlation length** $\xi$ — the lateral scale over which the interface
  "forgets" its height. For $r \ll \xi$, $g(r) \approx 2\sigma^2 (r/\xi)^{2H}$
  rises as a power law; for $r \gg \xi$ it saturates at $g \to 2\sigma^2$.
- **Hurst (roughness) exponent** $H \in (0,1]$ — the local jaggedness. Small
  $H$ is spiky/irregular at short scales; $H \to 1$ is smooth and rolling.
  The self-affine scaling $\delta h \sim r^{H}$ is the same $H$ that appears
  in the diffuse-scattering line shape in off-specular XRR.

`hhcf_fit` fits a **nugget-augmented** form,

$$g(r) = 2\sigma_n^2 + 2\sigma^2\Big[\,1 - \exp\!\big(-(r/\xi)^{2H}\big)\,\Big].$$

The nugget $\sigma_n$ absorbs the same column-uncorrelated jitter of Section
4: white jitter lifts $g(r)$ by a constant $2\sigma_{\mathrm{loc}}^2$ for
*every* $r \geq 1$ (it appears in $\langle h(x+r)^2\rangle$ and
$\langle h(x)^2\rangle$ but not in the cross term). Without the nugget the
fit warps $H$ downward and $\xi$ upward to chase the spurious jump between
$r=0$ and $r=1$. The fit is seeded from the noise floor
($\sigma_n \approx \sigma_{\mathrm{loc}}$) and the $1-1/e$ crossing of $g$
($\xi_0$).

**Why the fit range is restricted to $\sim 4\xi$.** Beyond a few correlation
lengths $g(r)$ is flat (saturated) and carries no information about $\xi$ or
$H$ — but it dominates an unweighted least-squares fit by sheer number of
points, and the tail also has few *independent* pairs (large-lag samples are
autocorrelated), so its scatter is deceptively small. `hhcf_fit` therefore
seeds $\xi_0$ from the saturation crossing and fits only over
$r \le \max(4\xi_0, 16)$ so the informative *rise* — which actually encodes
$\xi$ and $H$ — is not out-voted by the saturated plateau. (Independently, the
overall maximum lag is capped at $N/4$ for the same independent-pairs reason.)

---

## 6. Chemical vs geometric width: the $\sigma_{\mathrm{erf}}$ decomposition

`layers.py` fits an error function to the *laterally averaged* depth profile
to get each interface's transition width $\sigma_{\mathrm{erf}}$:

$$I(z) \propto \operatorname{erf}\!\Big(\frac{z - z_0}{\sqrt{2}\,\sigma_{\mathrm{erf}}}\Big).$$

But lateral averaging *convolves the true compositional grading with the
geometric waviness it smears out.* If an interface is atomically sharp in
composition ($\sigma_{\mathrm{chem}} \to 0$) but wavy, averaging over columns
whose edges scatter with rms $\sigma_w$ produces a graded-looking average
profile of width $\approx \sigma_w$. In general the two add in quadrature
(plus any residual tilt the average did not remove):

$$\sigma_{\mathrm{erf}}^2 \;\approx\; \sigma_{\mathrm{chem}}^2 + \sigma_w^2
  \quad\Longrightarrow\quad
  \sigma_{\mathrm{chem}} = \sqrt{\sigma_{\mathrm{erf}}^2 - \sigma_w^2}$$

(`sigma_chem`; returns NaN when $\sigma_w \ge \sigma_{\mathrm{erf}}$, i.e.
roughness-limited with nothing resolvable left). Only the per-column trace
lets you separate the two — the averaged profile alone cannot.

**This is exactly the XRR ambiguity.** In specular reflectometry the
Névot–Croce factor damps each Fresnel coefficient by a Debye–Waller-like term,

$$r_{ij} \;\longrightarrow\; r_{ij}\,\exp\!\big(-2\,k_{z,i}\,k_{z,j}\,\sigma^2\big),$$

where the single $\sigma$ is *indistinguishable* between a graded index
profile (chemical interdiffusion) and a laterally rough but chemically sharp
interface. Specular XRR cannot tell them apart — it needs *off-specular*
(diffuse) data to isolate the geometric part. The cross-section does the
separation directly in real space: $\sigma_{\mathrm{erf}}$ is the reflectivist's
Névot–Croce $\sigma$, and subtracting $\sigma_w^2$ recovers
$\sigma_{\mathrm{chem}}$, the true compositional interdiffusion width. Both
$\sigma_{\mathrm{erf}}$ and $\sigma_w$ are projection-limited (Section 8), so
$\sigma_{\mathrm{chem}}$ is an *upper* bound on grading.

---

## 7. Conformality and correlated-roughness scattering

When two interfaces (e.g. the bottom and top of a layer) are both traced, the
Pearson correlation between their detrended residuals

$$r = \frac{\sum_j \delta_a(x_j)\,\delta_b(x_j)}
            {\sqrt{\sum_j \delta_a^2(x_j)\;\sum_j \delta_b^2(x_j)}}$$

(`conformality`, on the common valid columns) measures how much the upper
interface **replicates** the lower one:

- $r \to 1$ — **conformal (replicated) roughness**: the growth front copied
  the substrate's undulations. The layer thickness is nearly constant even
  though both interfaces are rough (their roughness is common-mode). This is
  why `layers.py` reports thickness scatter from the robust std of the
  *difference* $h_b - h_a$, which cancels common-mode waviness and leaves only
  genuine wedge/thickness variation.
- $r \to 0$ — **uncorrelated roughness**: the interfaces roughen
  independently (e.g. kinetic roughening that erased the substrate memory).

The reflectometry link is direct. Vertically correlated (conformal) roughness
produces **resonant diffuse scattering** — the Yoneda-bounded sheets of
off-specular intensity concentrate onto "Holý bananas" (arcs of constant
$k_{z}$) at the Bragg-like conditions of the multilayer, because the replicated
interfaces scatter *in phase*. Uncorrelated roughness smears the diffuse
intensity out with no such resonance. Measuring $r$ from the cross-section
predicts qualitatively what an off-specular XRR map should look like, and
vice-versa: a strong resonant-diffuse sheet in XRR implies $r$ near $1$ here.

---

## 8. The TEM projection limitation

A (S)TEM image is a *projection* through the foil thickness $t$ along the
beam. Every measured column height is an average of the true interface over a
$\sim t$-deep slab:

$$h_{\mathrm{measured}}(x) = \frac{1}{t}\int_0^{t} h_{\mathrm{true}}(x, y)\,\mathrm{d}y.$$

For lateral roughness components of wavelength $\lambda$:

- $\lambda \gg t$ — the interface is nearly constant through the foil; the
  projection is faithful.
- $\lambda \lesssim t$ — the beam averages over many undulations along its
  path, and their contribution is suppressed roughly as $\operatorname{sinc}$
  of $t/\lambda$ (the projection is a boxcar average of depth $t$).

Two consequences, both **conservative**:

1. **$\sigma_w$ is a lower bound.** Short-wavelength roughness
   ($\lambda \lesssim t$) is washed out along the beam, so the measured rms
   underestimates the true rms. A $100$ nm foil cannot report roughness with
   $\lambda \lesssim 100$ nm faithfully.
2. **$\sigma_{\mathrm{erf}}$ is broadened.** Projection over a $t$-deep slab of
   a tilted or wavy interface widens the averaged transition, so
   $\sigma_{\mathrm{erf}}$ (and hence the inferred $\sigma_{\mathrm{chem}}$)
   is biased high.

The app exposes an **optional foil-thickness field**. When set, it marks the
untrustworthy region of the PSD — wavelengths $\lambda \lesssim t$ — so the
user knows which part of the spectrum is projection-corrupted and does not
over-interpret the high-frequency roll-off as physics. Thin the lamella
(smaller $t$) to push that cutoff to shorter wavelengths, at the cost of dose
and mechanical stability.

---

## 9. Block bootstrap for the confidence interval

The CI on $\sigma_w$ (`_block_bootstrap_ci`) cannot use the ordinary
i.i.d. bootstrap. Resampling columns independently destroys the very lateral
correlation that Sections 4–5 established: an i.i.d. resample looks *whiter*
than the data, so it *underestimates* the sampling variance of any
second-moment statistic and produces a CI that is too narrow (under-covers).
For $N$ samples with correlation length $\xi$ there are only $\sim N\Delta x/\xi$
*effective* independent samples, not $N$.

The **circular block bootstrap** (Künsch 1989; Efron & Tibshirani) preserves
short-range correlation by resampling *contiguous blocks* rather than single
columns. Blocks of length $\ell \approx N/8$ (comfortably $\gtrsim \xi$) are
drawn with random starts and wraparound, concatenated to length $N$, and
$\sigma_w$ is recomputed on each of `n_boot` (default $200$) resamples. The
$2.5$/$97.5$ percentiles of the bootstrap distribution give the reported
$95\%$ CI. Because each block carries its internal correlation intact, the
resampled variance tracks the true sampling variance and the interval attains
its nominal coverage.

Interpretation: a wide CI means too few effective samples (short trace, or
long $\xi$ relative to the FOV) — the number is soft. A tight CI means the FOV
contains many correlation lengths and $\sigma_w$ is well-determined.

---

## 10. Worked example and when to use

**Example (HAADF cross-section).** A $1024$ px-wide HAADF image of a
metal/oxide stack, calibrated at $\Delta x = 0.12$ nm/px ($L \approx 123$ nm
FOV). One interface is traced across all columns.

| Quantity | pixels | nm |
|---|---|---|
| robust rms $\sigma_{\mathrm{robust}}$ (after detrend) | $6.7$ | $0.80$ |
| noise floor $\sigma_{\mathrm{loc}}$ (lag-1) | $5.0$ | $0.60$ |
| **waviness $\sigma_w = \sqrt{\sigma_{\mathrm{robust}}^2 - \sigma_{\mathrm{loc}}^2}$** | $4.4$ | $\mathbf{0.53}$ |

$$\sigma_w = \sqrt{0.80^2 - 0.60^2}\ \text{nm} = \sqrt{0.28}\ \text{nm} \approx 0.53\ \text{nm}.$$

Note the noise floor ($0.60$ nm) is *most* of the raw scatter ($0.80$ nm):
without the correction one would report $\sigma \approx 0.80$ nm, overstating
the physical roughness by $50\%$. If the erf fit to the averaged profile gave
$\sigma_{\mathrm{erf}} = 0.90$ nm, then

$$\sigma_{\mathrm{chem}} = \sqrt{0.90^2 - 0.53^2}\ \text{nm} \approx 0.73\ \text{nm}$$

is the compositional interdiffusion width (upper bound), with the geometric
part removed. A quality flag $q = 0.94$ and a block-bootstrap CI of
$[0.44, 0.61]$ nm round out the report; an HHCF fit might give $\xi \approx 8$
nm, $H \approx 0.7$. If the lamella is $80$ nm thick, wavelengths below $\sim
80$ nm ($\gtrsim 60\%$ of the PSD here) are flagged projection-limited, so
$\xi$ and $\sigma_w$ are best read as lower bounds.

**When to use this measure**

- *Yes:* quantifying interface roughness / interdiffusion in an epitaxial or
  deposited stack; cross-checking an XRR-fit $\sigma$ against a real-space
  image; testing conformality of multilayer growth; comparing process splits
  (deposition temperature, anneal) on a common FOV and detrend order.
- *Marginal:* interfaces with true undulation at $\lambda \gtrsim L$ (the
  detrend eats it — widen the FOV) or $\lambda \lesssim t$ (projection eats it
  — thin the lamella).
- *No:* a single micrograph as an *absolute* roughness reference divorced from
  its bandwidth — always report FOV, pixel size, detrend order, foil
  thickness, quality flag, and CI alongside $\sigma_w$, or the number is not
  reproducible.

---

## References

1. S. K. Sinha, E. B. Sirota, S. Garoff, and H. B. Stanley, "X-ray and
   neutron scattering from rough surfaces," *Phys. Rev. B* **38**, 2297
   (1988). — self-affine HHCF $g(r)=2\sigma^2[1-\exp(-(r/\xi)^{2H})]$ and the
   diffuse-scattering line shape.

2. L. Névot and P. Croce, "Caractérisation des surfaces par réflexion
   rasante de rayons X," *Rev. Phys. Appl.* **15**, 761 (1980). — the
   Debye–Waller roughness factor $\exp(-2k_{z,i}k_{z,j}\sigma^2)$ and the
   chemical/geometric $\sigma$ ambiguity.

3. V. Holý and T. Baumbach, "Nonspecular X-ray reflection from rough
   multilayers," *Phys. Rev. B* **49**, 10668 (1994). — vertically correlated
   roughness and resonant diffuse scattering.

4. ISO 4287:1997, *Geometrical Product Specifications (GPS) — Surface
   texture: Profile method*; and D. J. Whitehouse, *Handbook of Surface and
   Nanometrology*, 2nd ed. (CRC Press, 2011). — the form / waviness /
   roughness wavelength-band separation and profile filtering.

5. P. J. Rousseeuw and C. Croux, "Alternatives to the median absolute
   deviation," *J. Am. Stat. Assoc.* **88**, 1273 (1993). — the $1.4826$ MAD
   normal-consistency factor and robust scale estimation.

6. H. R. Künsch, "The jackknife and the bootstrap for general stationary
   observations," *Ann. Statist.* **17**, 1217 (1989); and B. Efron and
   R. J. Tibshirani, *An Introduction to the Bootstrap* (Chapman & Hall,
   1993). — the (moving/circular) block bootstrap for dependent data.

7. J. Als-Nielsen and D. McMorrow, *Elements of Modern X-ray Physics*, 2nd
   ed. (Wiley, 2011), Ch. 3. — specular vs off-specular reflectivity and
   interface-width conventions, for the XRR reader.
