# EDS quantification and detector artifacts

This document covers two model-based EDS features in fermiviewer: the
**ζ-factor (Watanabe–Williams) quantification** that turns net peak
intensities into composition *and* mass-thickness, and the
**escape / sum-peak artifact handling** that keeps detector artifacts from
being mistaken for element lines. The pure libraries are
`calc/eds_zeta.py` and `calc/eds_artifacts.py`; the FastAPI adapters are
`/eds/zeta`, `/eds/artifacts`, and the `remove_artifacts` pre-pass on
`/eds/peakfit`, all in `routes/eds_advanced.py`. Uncertainty flows through
`calc/uncertainty.py`. Net areas come from the constrained multi-Gaussian
deconvolution in `calc/eds_peakfit.py`; peak widths from the Fiori–Newbury
detector-resolution model in `calc/eds_calib.py`.

The target reader has done a Cliff–Lorimer thin-film analysis and knows
what a k-factor is, but may not have met the absolute (ζ) formulation or
thought carefully about why a spurious peak sitting *on top of* a real line
must be treated differently from one sitting in an empty part of the
spectrum.

---

# Part I — ζ-factor quantification

## 1. Why ζ instead of Cliff–Lorimer

The Cliff–Lorimer ratio method

$$\frac{C_A}{C_B} = k_{AB}\,\frac{I_A}{I_B}$$

is the workhorse of analytical TEM, but it is a *ratio* method: it yields
composition and nothing else. It cannot report thickness, it cannot
compute its own absorption correction (the absorption path length depends
on the mass-thickness it never computes), and it discards the absolute
scale of the measurement — the beam current and acquisition time drop out
of the ratio.

The ζ-factor method (Watanabe & Williams 2006) keeps the absolute scale.
It relates each element's net intensity $I_i$ *directly* to that element's
mass-thickness through the electron dose $D_e$:

$$\boxed{\,C_i\,\rho t = \zeta_i\,\frac{I_i}{D_e}\,}$$

where $C_i$ is the mass fraction of element $i$, $\rho t$ is the specimen
mass-thickness (density × thickness), and $\zeta_i$ is the element's
ζ-factor. Because the dose and the absolute intensities are retained, the
same equation delivers thickness *for free*, as the next section shows.

## 2. Mass-thickness falls out of the closure condition

Sum the boxed relation over all analysed elements and impose the closure
condition $\sum_i C_i = 1$:

$$\sum_i C_i\,\rho t = \rho t = \frac{1}{D_e}\sum_j \zeta_j\,I_j
\qquad\Longrightarrow\qquad
\rho t = \frac{\sum_j \zeta_j I_j}{D_e}.$$

Mass-thickness is therefore obtained from the intensities alone — no
external thickness measurement, no standard geometry assumption beyond the
ζ-factors themselves. Substituting $\rho t$ back into the boxed relation
gives the composition as a normalised ζ-weighted intensity,

$$C_i = \frac{\zeta_i I_i}{\sum_j \zeta_j I_j},$$

which is the ζ-analogue of Cliff–Lorimer normalisation with $k \to \zeta$.
`zeta_quantify` computes both: `mean_mass_thickness` (in kg/m²) and the
per-element weight fractions, from which atomic fractions follow by the
usual division by atomic mass, $\mathrm{at}_i \propto C_i/M_i$.

**Units.** In Watanabe's SI convention $\zeta$ carries **kg·m⁻²** (per
incident electron, per detected photon), so $\rho t$ comes out in kg/m².
Multiply by $10^{5}$ for the microanalyst's µg/cm²; divide by a supplied
density $\rho$ (converted to kg/m³) to get a thickness in nm
(`thickness_map_nm`, `None` without a density).

## 3. The dose and the k↔ζ bridge

The electron dose is simply the number of beam electrons that struck the
analysed volume,

$$D_e = \frac{I\,\tau}{e},$$

with beam current $I$, live time $\tau$, and the elementary charge
$e = 1.602176634\times10^{-19}$ C (`dose_electrons`; the route builds it
from `probe_current_na` and `live_time_s`). A 1 nA·s dose is
$\approx 6.24\times10^{9}$ electrons.

Rigorous ζ-factor work measures each $\zeta_i$ from a pure-element or
compound standard of known thickness. Absent that, fermiviewer bootstraps
ζ from the k-factors it already ships. Both methods relate composition to
intensity, so the ζ-factors and k-factors are related exactly by

$$k_{ij} = \frac{\zeta_i}{\zeta_j}
\qquad\Longrightarrow\qquad
\zeta_i = k_i\,\zeta_{\mathrm{Si}},$$

where $k_i$ is the tabulated k-factor relative to Si. One absolute number
— an experimentally determined $\zeta_{\mathrm{Si}}$ for *this* detector at
*this* voltage — scales the entire built-in 200 kV k-factor table into
estimated ζ-values (`zeta_from_k_factors`; the `/eds/zeta` route accepts
either explicit per-element `zeta_factors` or a single `zeta_si`).

**ζ is detector-specific.** A ζ-factor absorbs the collection solid angle
$\Omega \approx A/d^{2}$ (active area over working distance²,
`detector_solid_angle_sr`) and the detector efficiency, so
$\zeta \propto 1/\Omega$. ζ-values measured on one detector are *not*
transferable to another without rescaling by $\Omega_{\mathrm{ref}}/\Omega$.
This is the price of the absolute scale, and it is why the bootstrap from
k-factors + one $\zeta_{\mathrm{Si}}$ is only an estimate: it inherits the
correct *relative* efficiencies from the k-table but pins the absolute
scale to a single, possibly imperfect, number.

## 4. Self-consistent thin-film absorption

Because ζ gives $\rho t$, it can — unlike Cliff–Lorimer — correct its own
X-ray absorption. Characteristic photons generated at depth must traverse
the specimen to reach the detector; the fraction that survives defines the
absorption correction factor $A_i$ that restores the *measured* intensity
to the *generated* intensity. For a thin film of uniform generation the
standard result is

$$A_i = \frac{\chi_i\,\rho t}{1 - \exp(-\chi_i\,\rho t)},
\qquad
\chi_i = \operatorname{cosec}\alpha\;\sum_j \Big(\frac{\mu}{\rho}\Big)_i^{\,j} w_j,$$

where $\alpha$ is the X-ray take-off angle, $(\mu/\rho)_i^{\,j}$ is the mass
absorption coefficient of element $i$'s line in absorber $j$, and $w_j$ is
the weight fraction of the absorber. $A_i \ge 1$ and $A_i \to 1$ as
$\chi_i \rho t \to 0$ (a vanishingly thin, non-absorbing film).

The correction is circular — $\chi_i$ needs the composition, the
composition needs the corrected intensities, and $\rho t$ needs both — so
`_iterate` solves it as a **fixed point**:

1. from the current generated-intensity estimate, form $\zeta_i I_i$,
   $\rho t = \sum_j \zeta_j I_j / D_e$, and $w_i = \zeta_i I_i / \sum_j \zeta_j I_j$;
2. build $\chi_i$ from the current $w$, set $x = \chi_i\,\rho t$, and
   $A_i = x/(1-e^{-x})$;
3. restore the generated intensity as $A_i \times (\text{measured }I_i)$ and repeat.

Composition and $\rho t$ converge in a handful of passes (`iterations=5`
by default). With `absorption=False` all $A_i = 1$ and the method reduces
to the pure closure of Section 2.

## 5. The MAC model caveat

The mass absorption coefficients feeding $\chi_i$ come from fermiviewer's
calibrated closed-form model (`mass_absorption_coeff`):

$$\Big(\frac{\mu}{\rho}\Big) = C\,\frac{Z^{4}\lambda^{3}}{A},
\qquad C = 1.0\times10^{22},\quad \lambda_{\text{cm}} = \frac{12.398}{E_{\text{keV}}}\times10^{-8}.$$

The constant $C$ is a **deliberate, calibrated value** (annotated
do-not-"fix" in the source), tuned so the $Z^4\lambda^3$ scaling matches
tabulated coefficients for the hard-X-ray K-lines that dominate
mid-$Z$ analysis. It is *not* a first-principles cross-section: below
about 1.5 keV — soft lines, absorption edges, the L- and M-line regime —
the single-power-law form overestimates $\mu/\rho$ (noted in the module
tests). Treat the absorption correction as reliable for hard lines and
approximate for soft ones; for soft-line-dominated systems, supply
measured ζ-factors (which fold the true absorption into the calibration)
rather than leaning on the iterated correction.

## 6. Uncertainty propagation

The ζ composition normalisation $w_i = \zeta_i I_i / \sum_j \zeta_j I_j$ is
algebraically identical to Cliff–Lorimer with the substitution $k \to
\zeta$, so it reuses the *same* delta-method core
(`cliff_lorimer_uncertainty` in `calc/uncertainty.py`). Each fraction is a
normalised sum $q_i/\sum q$, and the delta method gives

$$\operatorname{var}(\text{frac}_i) = \big[\mathbf{J}\,\mathbf{\Sigma}\,\mathbf{J}^{\!\top}\big]_{ii},
\qquad
J_{ij} = \frac{\delta_{ij} - \text{frac}_i}{\sum_k q_k},$$

with numerators $q_i = \zeta_i I_i$ for weight% and $q_i = (\zeta_i/M_i)I_i$
for atomic%. The per-element intensity variances $\operatorname{var}(I_i)$
are the squared 1σ fit errors on the deconvolved amplitudes (or Poisson
counting variances for window-integration). The absorption factors are
treated as **exact**: the route scales both the intensities and their
variances by $A_i$ (`net * a_f`, `var * a_f**2`) so that value and error
transform consistently, without inflating the error bar for the (unknown)
uncertainty of the correction itself.

Mass-thickness carries its own error bar. From $\rho t = \sum_j \zeta_j
(A_j I_j)/D_e$ with independent intensity variances,

$$\sigma_{\rho t} = \frac{1}{D_e}\sqrt{\sum_j \zeta_j^{2}\,A_j^{2}\,\operatorname{var}(I_j)}$$

(the route's `rho_t_sigma`). Dose and ζ are taken as exact here; in
rigorous work the ζ-factor calibration uncertainty is the dominant
systematic and should be added in quadrature.

## 7. When to use ζ, and its limits

- **Prefer ζ over Cliff–Lorimer when** you need the specimen thickness or
  mass-thickness as an output; when the dose (beam current × live time) is
  known and stable; when absorption is non-negligible and you want a
  self-consistent correction rather than an assumed thickness; or when you
  want composition and thickness *maps* from a spectrum image on a common
  absolute footing.
- **Stay with Cliff–Lorimer when** you only need a composition ratio, the
  dose is unknown or drifting, or you have no route to an absolute
  $\zeta_{\mathrm{Si}}$ and the k-table alone suffices.
- **Limitations.** ζ is detector- and voltage-specific (Section 3); the
  bootstrap from one $\zeta_{\mathrm{Si}}$ is an estimate, and rigorous work
  measures ζ from standards. The iterated absorption correction is only as
  good as the MAC model (Section 5). The closure condition assumes all
  significant elements are analysed — an unmeasured light element (C, O in
  an unanalysed matrix) biases both composition and $\rho t$.

---

# Part II — Escape and sum-peak artifacts

Two families of detector artifact routinely masquerade as element lines.
Both are *predicted* from the analysed elements' line energies, then either
*measured* or *modeled* depending on whether they overlap a real peak
(`calc/eds_artifacts.py`).

## 8. Silicon escape peaks

When a characteristic photon photo-ionises a Si atom in the detector's
active volume, the resulting Si-Kα fluorescence photon can *escape* the
detector before its energy is collected. The event is then recorded at the
parent energy minus the lost Si-Kα:

$$E_{\text{escape}} = E_{\text{parent}} - 1.740\ \text{keV}.$$

Escape can only happen if the parent photon has enough energy to ionise the
Si K shell in the first place, so escape peaks exist **only for parents
above the Si K edge**,

$$E_{\text{parent}} > 1.839\ \text{keV}$$

(`SI_ESCAPE_KEV = 1.740`, `SI_K_EDGE_KEV = 1.839`). The escape probability
is small — typically **0.1–2 %** of the parent's counts, falling with
parent energy — with a route-tunable default of 1 %
(`DEFAULT_ESCAPE_FRACTION = 0.01`). Rigorous work measures the fraction
from a pure standard.

## 9. Sum / pile-up peaks and the right width

When two photons of energies $E_i$ and $E_j$ arrive within one
pulse-shaping window, the pulse processor cannot separate them and records
a single event at their sum,

$$E_{\text{sum}} = E_i + E_j$$

(including self-sums $2E_i$, the same-line pile-up peak). These populate
the high-energy region above all the real lines, which is usually empty —
hence sum peaks are normally *measured* (Section 10).

The subtle point is the **width**. fermiviewer places every artifact
Gaussian at the Fano detector width evaluated *at the artifact's own
energy* — for a sum peak, at $E_i + E_j$. This is physically correct, and
the Fiori–Newbury resolution model shows why (`fano_fwhm`):

$$\mathrm{FWHM}(E)^2 = \mathrm{FWHM}_{\text{noise}}^2 + k\,F\,\varepsilon\,E,
\qquad k = \big(2\sqrt{2\ln 2}\big)^2.$$

The two terms have different origins. The **electronic-noise** term
$\mathrm{FWHM}_{\text{noise}}$ is a property of the readout chain and enters
**once per recorded event**, regardless of how many photons contributed.
The **charge-statistics** (Fano) term scales with the *total charge*
deposited in the shaping window. In a pile-up event both photons dump their
charge into one window, so the collected charge — and its statistical
spread — scales with $E_i + E_j$. Evaluating the model at $E = E_i + E_j$
therefore counts the electronic noise once and the charge statistics on the
full summed energy, which is exactly what a pile-up event does. (Naively
adding two single-photon widths in quadrature would double-count the
electronic noise and give too broad a peak.)

## 10. Measured vs modeled: the separability split

An artifact is handled one of two ways, decided by `partition_artifacts`.
An artifact is **blocked** if it lies within
$\text{clearance}\cdot(\sigma_{\text{artifact}} + \sigma_{\text{line}})$ of
any analysed element's line (default clearance = 2σ); otherwise it is
**free**.

**Free artifacts are measured.** Clear of every real line, they are fitted
as free-amplitude Gaussians (fixed centre, fixed Fano width, amplitude
$\ge 0$) jointly with a linear background — but *on the residual*
`spectrum − characteristic-peak model`, not the raw spectrum. Fitting the
residual guarantees the free Gaussians cannot leak real characteristic
counts into an artifact area (`measure_artifacts`).

**Blocked artifacts cannot be freely fitted.** The canonical trap is the
Cu-Kα escape at $8.048 - 1.740 = 6.308$ keV sitting almost on top of Fe-Kα
at 6.404 keV — a 0.096 keV gap, well inside a couple of detector σ. A
free-amplitude Gaussian there would **steal amplitude** from the real Fe
line: two nearly-coincident Gaussians are strongly anti-correlated in a
least-squares fit, and the optimiser will trade real Fe-Kα counts into the
escape Gaussian (or vice versa), biasing *both* areas. The joint fit is
ill-conditioned precisely where the peaks overlap, so a free fit is
forbidden.

Instead a blocked **escape** is *modeled*, not fitted:

$$A_{\text{escape}} = f_{\text{escape}}\times A_{\text{parent}},$$

the escape fraction times the parent's net area (from the initial
characteristic fit). The full modeled escape curve is subtracted from the
*raw* spectrum, and the characteristic peaks are refit on the corrected
spectrum. Blocked **sum** peaks have no such parent-area proxy, so they are
**skipped and flagged** (`ArtifactRemoval.skipped`) — left in the data with
a warning rather than silently altered.

**Why subtract the full modeled area even though the first fit already
absorbed some escape counts?** This is the subtle LSQ point. The initial
characteristic-only fit is a least-squares *projection* of the spectrum
onto the model basis. Because the escape bump lies under the Fe-Kα
Gaussian, that projection soaks a fraction of the escape counts into the
Fe-Kα amplitude — the initial Fe area is inflated by roughly half the
escape counts (the exact fraction is the overlap integral of the two
Gaussians). But we never *use* that contaminated Fe amplitude as the escape
estimate; the escape area is computed **independently** from the physics
($f_{\text{escape}}\times A_{\text{parent}}$). We subtract the *entire*
modeled escape curve from the raw spectrum and refit. The refit then sees a
spectrum with the escape gone, so the Fe-Kα amplitude relaxes *down* to its
true value. Subtracting only "the half the first fit missed" would be wrong
— it would leave the inflated Fe amplitude uncorrected. Subtracting the
full modeled area and refitting is the self-consistent operation: the
escape counts are removed from the data exactly once, and the LSQ re-
projection redistributes the rest correctly. (Because the escape fraction
is ~1 %, the parent-area feedback is tiny and a single refit pass
suffices.)

## 11. When to enable, and the caveat

- **Enable the pre-pass** (`remove_artifacts=True` on `/eds/peakfit` or
  `/eds/zeta`) when the spectrum spans energies where escapes or sums can
  land on or near analysed lines — high count rates (pile-up), a hard line
  whose escape coincides with a softer element's line (the Cu→Fe trap), or
  any quantification where a few percent of misattributed counts matters.
  Use the bremsstrahlung background on `/eds/artifacts` when a continuum is
  present: a clean residual is what makes the free artifact areas
  trustworthy.
- **Caveat.** Blocked sum peaks are *not* removed — they cannot be modeled
  from a single parent area, so they remain in the data and are returned in
  `skipped` for the UI to flag. Do not read their absence from the
  corrected spectrum as their absence from the physics; inspect the flagged
  list and, if a skipped sum overlaps a line you care about, reduce the
  count rate and re-acquire rather than trusting the deconvolution there.

---

## References

1. M. Watanabe and D. B. Williams, "The quantitative analysis of thin
   specimens: a review of progress from the Cliff–Lorimer to the new
   ζ-factor methods," *J. Microsc.* **221**, 89–109 (2006). — the ζ-factor
   method, the $C_i\rho t = \zeta_i I_i/D_e$ relation, mass-thickness from
   closure, and the self-consistent absorption correction.

2. J. I. Goldstein, D. E. Newbury, J. R. Michael, N. W. M. Ritchie,
   J. H. J. Scott, and D. C. Joy, *Scanning Electron Microscopy and X-Ray
   Microanalysis*, 4th ed. (Springer, 2018). — Ch. 7 (escape and sum
   peaks, detector artifacts) and Ch. 19 (thin-film quantification and
   absorption corrections).

3. P. J. Statham, "Deconvolution and background subtraction by least-
   squares fitting with prefiltering of spectra," and the pile-up /
   pulse pile-up treatment, *J. Res. NIST* **107**, 531 (2002). — sum /
   pile-up peak formation and correction.

4. G. Cliff and G. W. Lorimer, "The quantitative analysis of thin
   specimens," *J. Microsc.* **103**, 203–207 (1975). — the ratio method
   that ζ generalises.

5. S. J. B. Reed, *Electron Microprobe Analysis and Scanning Electron
   Microscopy in Geology*, 2nd ed. (Cambridge, 2005), Ch. 8. — the thin-
   film absorption factor $A = \chi\rho t/(1-e^{-\chi\rho t})$ and the
   $\operatorname{cosec}\alpha$ path-length geometry.
