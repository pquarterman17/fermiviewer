"""Getting a depth profile out of a cross-section image.

Split from `calc/layers.py` when 4C-4 pushed it past the 500-line
ratchet, along a seam that was already there: everything here answers
"what does this image look like along its growth axis", and everything
left in `layers` answers "where are the interfaces in that profile".

`cross_section_profile` is the rectangular collapse and routes
`mean`/`sum` through the golden-tested `box_integrate`. An irregular
region goes to `calc.region_profile` instead, which is why the mask
argument appears here but the masked arithmetic does not.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.profile_stats import box_integrate
from fermiviewer.calc.region_profile import masked_depth_profile
from fermiviewer.calc.roi import extract_rect_roi, roi_slices
from fermiviewer.calc.texture import structure_tensor

#: ±pi/2 wrap constant for the orientation maths below.
_HALF_PI = np.pi / 2.0

__all__ = [
    "OrientationResult",
    "cross_section_profile",
    "destripe",
    "detect_growth_orientation",
]


def _wrap_to_pm_half_pi(a: float) -> float:
    """Wrap an angle (radians) into (-π/2, π/2]."""
    a = (a + _HALF_PI) % np.pi - _HALF_PI
    return float(a)


@dataclass(frozen=True)
class OrientationResult:
    axis: str                 # "y" (layers horizontal) | "x" (layers vertical)
    layers_horizontal: bool
    tilt_deg: float           # signed layer tilt off-axis; rotate by -tilt to level
    coherence: float          # 0..1, how strongly oriented the field is


def detect_growth_orientation(
    img: np.ndarray, sigma: float = 3.0
) -> OrientationResult:
    """Detect the growth (stacking) axis from the dominant gradient.

    Layer interfaces produce strong gradients along the growth axis, so the
    coherence-weighted dominant structure-tensor orientation gives both the
    axis (vertical vs horizontal layers) and the small off-axis tilt to
    level. ``θ`` is the gradient direction from +x; ``θ≈±π/2`` ⇒ vertical
    gradient ⇒ horizontal layers (axis ``"y"``).

    NaN policy (deliberate extension beyond the MATLAB reference — this is a
    net-new function with no fermi-viewer analogue): ``structure_tensor``'s
    gradient/Gaussian pipeline is not NaN-aware, so a single non-finite pixel
    would silently corrupt the coherence-weighted orientation over a whole
    neighbourhood rather than just at that pixel. Proper NaN handling would
    mean threading a mask through ``calc.texture.structure_tensor`` (out of
    scope here), so this fails loudly instead.
    """
    arr = np.asarray(img, dtype=np.float64)
    if not np.all(np.isfinite(arr)):
        raise ValueError("detect_growth_orientation: image contains non-finite values")
    st = structure_tensor(arr, sigma)
    w = st.coherence.ravel()
    two_theta = 2.0 * st.orientation.ravel()
    # coherence-weighted circular mean of the (mod-π) orientation
    c = float(np.sum(w * np.cos(two_theta)))
    s = float(np.sum(w * np.sin(two_theta)))
    dom_theta = 0.5 * np.arctan2(s, c)          # gradient direction, (-π/2, π/2]
    coherence = float(np.hypot(c, s) / (w.sum() + np.finfo(np.float64).eps))

    layers_horizontal = abs(dom_theta) > np.pi / 4.0   # gradient ~vertical
    axis = "y" if layers_horizontal else "x"
    # layer lines run perpendicular to the gradient
    layer_angle = _wrap_to_pm_half_pi(dom_theta + _HALF_PI)
    tilt = layer_angle if layers_horizontal else _wrap_to_pm_half_pi(layer_angle - _HALF_PI)
    return OrientationResult(axis, layers_horizontal, float(np.degrees(tilt)), coherence)


def _roi_subimage(arr: np.ndarray, roi: tuple[int, int, int, int] | None) -> np.ndarray:
    """The ROI sub-image, clamped exactly like ``box_integrate`` (1-based,
    inclusive) so trace indices line up with the depth profile."""
    return extract_rect_roi(arr, roi)


def cross_section_profile(
    img: np.ndarray,
    roi: tuple[int, int, int, int] | None = None,
    axis: str = "y",
    reduce: str = "mean",
    mask: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Lateral-collapse an ROI to a 1-D depth profile along ``axis``.

    ``axis="y"`` reduces over columns → one value per row (depth top→bottom,
    for horizontal layers); ``axis="x"`` reduces over rows. ``roi`` is a
    1-based ``(r1, c1, r2, c2)`` rect (whole image if ``None``). Returns
    ``(depth_pos_px, profile)``.

    ``reduce`` is ``"mean"`` / ``"sum"`` (via the golden-tested
    :func:`box_integrate`) or ``"median"`` — a *robust* collapse that ignores
    outlier columns/rows (e.g. strong localised FIB curtains) where the mean
    is pulled. Positions stay 0-based pixels from the box edge.

    NaN policy (deliberate extension beyond the MATLAB reference, same
    convention as the 2026-06 grain-finding hardening): ``reduce="median"``
    uses ``nanmedian`` so a dead/hot pixel in one column doesn't blank the
    whole depth row — fitting, since "robust to outliers" is exactly this
    mode's purpose. ``"mean"``/``"sum"`` delegate to the golden-tested
    :func:`box_integrate`, which is not NaN-aware and must not be touched
    here, so a non-finite ROI raises instead of silently propagating.
    """
    arr = np.asarray(img, dtype=np.float64)
    if arr.ndim != 2:
        raise ValueError("layer analysis needs a 2-D image")
    if axis not in ("x", "y"):
        raise ValueError("axis must be 'y' or 'x'")
    if mask is not None:
        # 4C-4: an irregular region collapses through `calc.region_profile`,
        # which keeps mean/median and refuses `sum`. The rectangular path
        # below is untouched, so `box_integrate` stays golden-tested.
        rows, cols = roi_slices(arr.shape, roi)
        return masked_depth_profile(arr[rows, cols], mask[rows, cols], axis, reduce)
    if reduce == "median":
        sub = _roi_subimage(arr, roi)
        if axis == "y":
            has_data = (~np.isnan(sub)).any(axis=1)
            prof = np.full(sub.shape[0], np.nan)
            prof[has_data] = np.nanmedian(sub[has_data], axis=1)
        else:
            has_data = (~np.isnan(sub)).any(axis=0)
            prof = np.full(sub.shape[1], np.nan)
            prof[has_data] = np.nanmedian(sub[:, has_data], axis=0)
        return np.arange(prof.size, dtype=np.float64), prof
    h, w = arr.shape
    r1, c1, r2, c2 = roi if roi is not None else (1, 1, h, w)
    if not np.all(np.isfinite(_roi_subimage(arr, roi))):
        raise ValueError(
            "cross_section_profile: non-finite values in ROI; use "
            "reduce='median' or pre-sanitize (calc.normalize.sanitize)"
        )
    x_pos, x_int, y_pos, y_int, _ = box_integrate(arr, r1, c1, r2, c2, reduce=reduce)
    return (y_pos, y_int) if axis == "y" else (x_pos, x_int)


def destripe(
    img: np.ndarray,
    axis: str = "y",
    *,
    cutoff: float = 4.0,
    band: float = 1.0,
    strength: float = 1.0,
) -> np.ndarray:
    """Suppress FIB *curtaining* (streaks parallel to the depth axis) via an FFT notch.

    FIB-milling-rate variations leave streaks running parallel to the growth
    (depth) axis. Such streaks are ~constant along their length, so in the 2-D
    Fourier transform their energy concentrates on the zero-frequency *line*
    perpendicular to the depth axis. A smooth Gaussian notch damps that line
    beyond ``cutoff`` cycles/FOV — removing the stripe texture that biases the
    lateral profile and inflates the per-column σ_w trace — while leaving DC,
    broad illumination, and the layer interfaces (which vary *along* the depth
    axis, off the notched line) intact.

    ``axis`` is the depth axis (``"y"`` ⇒ vertical streaks; ``"x"`` ⇒
    horizontal). ``cutoff`` is the lateral frequency below which structure is
    preserved; ``band`` is the notch half-width across the perpendicular
    frequency (px); ``strength`` 0..1 scales notch depth (1 = full removal).
    Targets the *measurement* (profile + trace), not the orientation estimate.
    Returns a float image of the same shape.

    NaN policy (deliberate extension beyond the MATLAB reference — net-new
    function): ``fft2`` has global support, so a SINGLE non-finite pixel
    corrupts every output pixel, not just its neighbourhood. Fail loudly
    instead of silently returning an all-NaN image.
    """
    arr = np.asarray(img, dtype=np.float64)
    if arr.ndim != 2:
        raise ValueError("destripe needs a 2-D image")
    if axis not in ("x", "y"):
        raise ValueError("axis must be 'x' or 'y'")
    if not np.all(np.isfinite(arr)):
        raise ValueError("destripe: image contains non-finite values")
    s = float(np.clip(strength, 0.0, 1.0))
    if s <= 0.0:
        return arr.copy()
    h, w = arr.shape
    f = np.fft.fftshift(np.fft.fft2(arr))
    kr = (np.arange(h) - h // 2).astype(np.float64)   # row frequency (centred)
    kc = (np.arange(w) - w // 2).astype(np.float64)   # col frequency (centred)
    rr, cc = np.meshgrid(kr, kc, indexing="ij")
    # vertical streaks (axis="y") concentrate on the kr≈0 line; localise the
    # notch across that perpendicular frequency, high-pass guard the lateral one
    along, across = (rr, cc) if axis == "y" else (cc, rr)
    line = np.exp(-0.5 * (along / max(band, 1e-6)) ** 2)        # ~1 on the 0-line
    keep_low = np.exp(-0.5 * (across / max(cutoff, 1e-6)) ** 2)  # preserve DC/broad
    notch = 1.0 - s * line * (1.0 - keep_low)
    return np.asarray(np.fft.ifft2(np.fft.ifftshift(f * notch)).real, dtype=np.float64)


