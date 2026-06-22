"""Cross-section thin-film layer analysis (PLAN_CROSS_SECTION_LAYERS).

Identify the layers in a cross-sectional EM image, measure each layer's
average thickness, and the per-interface transition sharpness σ_erf. The
pipeline is mostly orchestration of existing golden-tested primitives::

    img → detect_growth_orientation (structure_tensor) → depth axis + tilt
        → cross_section_profile (box_integrate, lateral mean) → I(depth)
        → detect_interfaces (smoothed gradient peaks)
        → per interface: fit_interface_width (erf) → sub-pixel centre + σ_erf
        → layers between consecutive interfaces → thickness = Δcentre·px

There is **no MATLAB golden** (net-new beyond parity) — verify against
synthetic ground truth (interfaces at known depths / known erf width).
σ_erf is resolution-limited (convolved with the probe/PSF); the Tier-2
σ_w waviness measure is not. Pure library (numpy/scipy + sibling calc).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.profiles import box_integrate, fit_interface_width
from fermiviewer.calc.texture import structure_tensor

__all__ = [
    "Interface",
    "Layer",
    "LayerResult",
    "OrientationResult",
    "analyze_layers",
    "cross_section_profile",
    "detect_growth_orientation",
    "detect_interfaces",
    "trace_interface",
]

_HALF_PI = np.pi / 2.0


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
    """
    st = structure_tensor(np.asarray(img, dtype=np.float64), sigma)
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
    h, w = arr.shape
    r1, c1, r2, c2 = roi if roi is not None else (1, 1, h, w)
    r1, r2 = sorted((int(round(r1)), int(round(r2))))
    c1, c2 = sorted((int(round(c1)), int(round(c2))))
    r1, r2 = max(r1, 1), min(r2, h)
    c1, c2 = max(c1, 1), min(c2, w)
    return arr[r1 - 1 : r2, c1 - 1 : c2]


def cross_section_profile(
    img: np.ndarray,
    roi: tuple[int, int, int, int] | None = None,
    axis: str = "y",
    reduce: str = "mean",
) -> tuple[np.ndarray, np.ndarray]:
    """Lateral-collapse an ROI to a 1-D depth profile along ``axis``.

    ``axis="y"`` reduces over columns → one value per row (depth top→bottom,
    for horizontal layers); ``axis="x"`` reduces over rows. ``roi`` is a
    1-based ``(r1, c1, r2, c2)`` rect (whole image if ``None``). Returns
    ``(depth_pos_px, profile)``.
    """
    arr = np.asarray(img, dtype=np.float64)
    if arr.ndim != 2:
        raise ValueError("layer analysis needs a 2-D image")
    h, w = arr.shape
    r1, c1, r2, c2 = roi if roi is not None else (1, 1, h, w)
    x_pos, x_int, y_pos, y_int, _ = box_integrate(arr, r1, c1, r2, c2, reduce=reduce)
    if axis == "y":
        return y_pos, y_int
    if axis == "x":
        return x_pos, x_int
    raise ValueError("axis must be 'y' or 'x'")


def detect_interfaces(
    profile: np.ndarray,
    sensitivity: float = 0.3,
    n_layers: int = 0,
    smooth: float = 1.5,
    min_separation: int = 5,
) -> np.ndarray:
    """Interface positions (integer profile indices) = gradient-peak depths.

    The smoothed depth profile's |gradient| peaks mark interfaces.
    ``sensitivity`` is the peak-height threshold as a fraction of the max
    gradient (lower → more interfaces). ``n_layers`` (>1) keeps only the
    ``n_layers-1`` strongest peaks; ``min_separation`` rejects near-duplicates.
    """
    from scipy.ndimage import gaussian_filter1d
    from scipy.signal import find_peaks

    prof = np.asarray(profile, dtype=np.float64).ravel()
    if prof.size < 5:
        return np.array([], dtype=int)
    grad = np.abs(np.gradient(gaussian_filter1d(prof, max(smooth, 1e-6))))
    gmax = float(grad.max())
    if gmax <= 0:
        return np.array([], dtype=int)
    peaks, props = find_peaks(
        grad, height=sensitivity * gmax, distance=max(1, int(min_separation))
    )
    if n_layers > 1 and peaks.size > n_layers - 1:
        order = np.argsort(props["peak_heights"])[::-1][: n_layers - 1]
        peaks = np.sort(peaks[order])
    return np.asarray(peaks, dtype=int)


@dataclass(frozen=True)
class Interface:
    position: float        # sub-pixel depth (profile pixels)
    sigma_erf: float       # erf transition width in calibrated units (sharpness)
    r_squared: float
    sigma_w: float = float("nan")          # geometric waviness, calibrated (Tier 2)
    trace: np.ndarray | None = None        # per-lateral-column edge depths (px)


@dataclass(frozen=True)
class Layer:
    index: int
    top: float             # bounding interface positions (profile pixels)
    bottom: float
    thickness: float       # (bottom - top) × pixel_size, calibrated units
    thickness_std: float = float("nan")    # FOV thickness std, calibrated (Tier 2)


@dataclass(frozen=True)
class LayerResult:
    axis: str
    layers_horizontal: bool
    tilt_deg: float
    coherence: float
    depth_pos: np.ndarray
    depth_profile: np.ndarray
    interfaces: list[Interface]
    layers: list[Layer]
    pixel_size: float
    unit: str


def _parabolic_edge(line: np.ndarray, approx: int, window: int) -> float:
    """Sub-pixel gradient-peak edge in a 1-D profile near ``approx``.

    The cheap per-column estimator (vs the expensive erf fit): the
    |gradient| maximum within ``±window`` of ``approx``, refined by a
    3-point parabolic fit. Fast enough to run on every lateral column.
    """
    n = line.size
    lo = max(1, approx - window)
    hi = min(n - 1, approx + window + 1)
    if hi - lo < 1:
        return float(approx)
    g = np.abs(np.gradient(line))
    k = int(np.argmax(g[lo:hi])) + lo
    if k <= 0 or k >= n - 1:
        return float(k)
    y0, y1, y2 = g[k - 1], g[k], g[k + 1]
    denom = y0 - 2.0 * y1 + y2
    frac = 0.5 * (y0 - y2) / denom if abs(denom) > 1e-12 else 0.0
    return float(k + np.clip(frac, -0.5, 0.5))


def trace_interface(
    img: np.ndarray,
    axis: str,
    interface_pos: float,
    window: int = 10,
    smooth: float = 1.0,
) -> np.ndarray:
    """Trace an interface column-by-column → its depth at each lateral pos.

    For ``axis="y"`` (horizontal layers) each column is a depth profile and
    the interface is traced across columns; ``axis="x"`` traces across rows.
    The std of the returned depths is the geometric waviness σ_w (in pixels).
    A light Gaussian pre-smooth suppresses per-column noise.
    """
    from scipy.ndimage import gaussian_filter1d

    arr = np.asarray(img, dtype=np.float64)
    lines = arr.T if axis == "y" else arr   # rows of `lines` are depth profiles
    approx = int(round(interface_pos))
    out = np.empty(lines.shape[0], dtype=np.float64)
    for j in range(lines.shape[0]):
        line = lines[j]
        if smooth > 0:
            line = gaussian_filter1d(line, smooth)
        out[j] = _parabolic_edge(line, approx, window)
    return out


def _refine_interface(
    depth_pos: np.ndarray, profile: np.ndarray, idx: int, window: int
) -> tuple[float, float, float]:
    """Sub-pixel interface centre + erf σ via the ported 4-param erf fit.

    Falls back to the raw peak position (σ = NaN) if the local window is too
    small or the fit fails to converge usefully.
    """
    lo = max(0, idx - window)
    hi = min(profile.size, idx + window + 1)
    if hi - lo < 5:
        return float(depth_pos[idx]), float("nan"), 0.0
    seg = profile[lo:hi]
    # the ported erf fit expects a rising step; negate a falling interface
    # (centre and σ are sign-independent) so down-steps fit too
    sign = 1.0 if seg[-1] >= seg[0] else -1.0
    try:
        fit = fit_interface_width(depth_pos[lo:hi], sign * seg, model="erf")
    except (ValueError, RuntimeError):
        return float(depth_pos[idx]), float("nan"), 0.0
    # a center that escaped the window means a failed fit — keep the peak
    if not (depth_pos[lo] <= fit.center <= depth_pos[hi - 1]):
        return float(depth_pos[idx]), float("nan"), float(fit.r_squared)
    return float(fit.center), float(fit.sigma), float(fit.r_squared)


def analyze_layers(
    img: np.ndarray,
    *,
    roi: tuple[int, int, int, int] | None = None,
    axis: str = "auto",
    sensitivity: float = 0.3,
    n_layers: int = 0,
    reduce: str = "mean",
    pixel_size: float = 1.0,
    unit: str = "px",
    fit_window: int = 15,
    orient_sigma: float = 3.0,
    waviness: bool = False,
    trace_window: int = 10,
) -> LayerResult:
    """Full cross-section layer analysis (thickness + σ_erf; optional σ_w).

    Auto-detects the growth axis (override with ``axis="y"|"x"``), collapses
    the ROI to a depth profile, detects interfaces, refines each with the
    erf fit, and reports the layers between consecutive interfaces with
    ``thickness = Δcentre × pixel_size``. With ``waviness`` (Tier 2) each
    interface is also traced column-by-column → geometric roughness σ_w and
    per-layer thickness std across the FOV. ``sigma_erf``/``sigma_w`` are in
    calibrated units; positions stay in profile pixels.
    """
    arr = np.asarray(img, dtype=np.float64)
    orient = detect_growth_orientation(arr, orient_sigma)
    use_axis = orient.axis if axis == "auto" else axis
    if use_axis not in ("x", "y"):
        raise ValueError("axis must be 'auto', 'x', or 'y'")

    depth_pos, profile = cross_section_profile(arr, roi, use_axis, reduce)
    peaks = detect_interfaces(profile, sensitivity, n_layers)

    # the ROI sub-image (clamped like box_integrate) for column-by-column tracing
    sub = _roi_subimage(arr, roi) if waviness else None

    interfaces: list[Interface] = []
    for p in peaks:
        center, sigma, r2 = _refine_interface(depth_pos, profile, int(p), fit_window)
        sigma_w = float("nan")
        trace: np.ndarray | None = None
        if sub is not None:
            trace = trace_interface(sub, use_axis, center, trace_window)
            sigma_w = float(np.std(trace)) * pixel_size
        interfaces.append(
            Interface(
                position=center,
                sigma_erf=sigma * pixel_size if np.isfinite(sigma) else float("nan"),
                r_squared=r2,
                sigma_w=sigma_w,
                trace=trace,
            )
        )
    interfaces.sort(key=lambda it: it.position)

    layers: list[Layer] = []
    for i in range(len(interfaces) - 1):
        top = interfaces[i].position
        bottom = interfaces[i + 1].position
        t_std = float("nan")
        tr_top, tr_bot = interfaces[i].trace, interfaces[i + 1].trace
        if tr_top is not None and tr_bot is not None and tr_top.size == tr_bot.size:
            t_std = float(np.std(tr_bot - tr_top)) * pixel_size
        layers.append(
            Layer(index=i, top=top, bottom=bottom,
                  thickness=(bottom - top) * pixel_size, thickness_std=t_std)
        )

    return LayerResult(
        axis=use_axis,
        layers_horizontal=(use_axis == "y"),
        tilt_deg=orient.tilt_deg,
        coherence=orient.coherence,
        depth_pos=depth_pos,
        depth_profile=profile,
        interfaces=interfaces,
        layers=layers,
        pixel_size=pixel_size,
        unit=unit,
    )
