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

from fermiviewer.calc.layers_detect import (
    detect_interfaces,
    detect_interfaces_scale_space,
)
from fermiviewer.calc.profiles import box_integrate, fit_interface_width
from fermiviewer.calc.texture import structure_tensor
from fermiviewer.calc.trace_roughness import (
    robust_sigma,
    robust_sigma_w,
    trace_interface,
)

__all__ = [
    "Interface",
    "Layer",
    "LayerResult",
    "OrientationResult",
    "analyze_layers",
    "cross_section_profile",
    "destripe",
    "detect_growth_orientation",
    "detect_interfaces",
    "detect_interfaces_scale_space",
    "recompute_layers",
    "trace_interface",
]

# modality → interface-detector preset. BF/DF have thickness fringes +
# diffraction contrast that create false interfaces in raw intensity, so
# they use multi-scale persistence; HAADF/EELS are monotonic per layer.
_MODALITY_PRESETS: dict[str, dict[str, object]] = {
    "haadf": {"scale_space": False},
    "eels": {"scale_space": False},
    "bf": {"scale_space": True, "scales": (2.0, 4.0, 8.0)},
    "df": {"scale_space": True, "scales": (2.0, 4.0, 8.0)},
}

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

    ``reduce`` is ``"mean"`` / ``"sum"`` (via the golden-tested
    :func:`box_integrate`) or ``"median"`` — a *robust* collapse that ignores
    outlier columns/rows (e.g. strong localised FIB curtains) where the mean
    is pulled. Positions stay 0-based pixels from the box edge.
    """
    arr = np.asarray(img, dtype=np.float64)
    if arr.ndim != 2:
        raise ValueError("layer analysis needs a 2-D image")
    if axis not in ("x", "y"):
        raise ValueError("axis must be 'y' or 'x'")
    if reduce == "median":
        sub = _roi_subimage(arr, roi)
        prof = np.median(sub, axis=1) if axis == "y" else np.median(sub, axis=0)
        return np.arange(prof.size, dtype=np.float64), prof
    h, w = arr.shape
    r1, c1, r2, c2 = roi if roi is not None else (1, 1, h, w)
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
    """
    arr = np.asarray(img, dtype=np.float64)
    if arr.ndim != 2:
        raise ValueError("destripe needs a 2-D image")
    if axis not in ("x", "y"):
        raise ValueError("axis must be 'x' or 'y'")
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


def _interfaces_and_layers(
    depth_pos: np.ndarray,
    profile: np.ndarray,
    idxs: np.ndarray,
    sub: np.ndarray | None,
    axis: str,
    pixel_size: float,
    fit_window: int,
    trace_window: int,
) -> tuple[list[Interface], list[Layer]]:
    """Refine interfaces at ``idxs`` and build the layers between them.

    Shared by :func:`analyze_layers` (auto-detected ``idxs``) and
    :func:`recompute_layers` (user-edited ``idxs``).
    """
    # adaptive per-interface trace window: never wider than half the gap to
    # the nearest neighbour, or a thin layer's trace locks onto the stronger
    # adjacent interface (the |gradient| max inside the window wins)
    srt = np.sort(np.asarray(idxs, dtype=np.float64))
    gaps: dict[int, int] = {}
    for i, v in enumerate(srt):
        near = min(
            v - srt[i - 1] if i > 0 else np.inf,
            srt[i + 1] - v if i < srt.size - 1 else np.inf,
        )
        gaps[int(v)] = int(near // 2) if np.isfinite(near) else trace_window
    interfaces: list[Interface] = []
    for idx in idxs:
        half_gap = gaps.get(int(idx), fit_window)
        # the erf fit window must also respect the neighbour gap, or both
        # fits around a thin layer converge onto the same (stronger) step
        center, sigma, r2 = _refine_interface(
            depth_pos, profile, int(idx), max(3, min(fit_window, half_gap))
        )
        sigma_w = float("nan")
        trace: np.ndarray | None = None
        if sub is not None:
            win = max(3, min(trace_window, half_gap))
            trace = trace_interface(sub, axis, center, win)
            # detrended + outlier-robust + noise-floor-corrected (item #8);
            # the raw std conflated tilt/bow + hot columns with roughness
            sigma_w = robust_sigma_w(trace) * pixel_size
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
            # robust (MAD) std: differencing already cancels common tilt/bow,
            # but a single bad column in either trace would poison a raw std.
            # A real thickness wedge (non-parallel interfaces) stays in — it
            # IS thickness variation, not a measurement artifact.
            t_std = robust_sigma(tr_bot - tr_top) * pixel_size
        layers.append(
            Layer(index=i, top=top, bottom=bottom,
                  thickness=(bottom - top) * pixel_size, thickness_std=t_std)
        )
    return interfaces, layers


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
    modality: str = "haadf",
    destripe_fib: bool = False,
    destripe_strength: float = 1.0,
    destripe_cutoff: float = 4.0,
) -> LayerResult:
    """Full cross-section layer analysis (thickness + σ_erf; optional σ_w).

    Auto-detects the growth axis (override with ``axis="y"|"x"``), collapses
    the ROI to a depth profile, detects interfaces, refines each with the
    erf fit, and reports the layers between consecutive interfaces with
    ``thickness = Δcentre × pixel_size``. With ``waviness`` (Tier 2) each
    interface is also traced column-by-column → geometric roughness σ_w and
    per-layer thickness std across the FOV. ``sigma_erf``/``sigma_w`` are in
    calibrated units; positions stay in profile pixels.

    ``destripe_fib`` removes FIB curtaining (:func:`destripe`) from the working
    image before profiling/tracing — pair with ``reduce="median"`` on heavily
    streaked specimens. Orientation/tilt are still read from the raw image.
    """
    arr = np.asarray(img, dtype=np.float64)
    orient = detect_growth_orientation(arr, orient_sigma)
    use_axis = orient.axis if axis == "auto" else axis
    if use_axis not in ("x", "y"):
        raise ValueError("axis must be 'auto', 'x', or 'y'")

    work = (
        destripe(arr, use_axis, cutoff=destripe_cutoff, strength=destripe_strength)
        if destripe_fib
        else arr
    )
    depth_pos, profile = cross_section_profile(work, roi, use_axis, reduce)
    preset = _MODALITY_PRESETS.get(modality.lower(), _MODALITY_PRESETS["haadf"])
    if preset["scale_space"]:
        scales = preset.get("scales", (2.0, 4.0, 8.0))
        peaks = detect_interfaces_scale_space(
            profile, scales, sensitivity, n_layers  # type: ignore[arg-type]
        )
    else:
        peaks = detect_interfaces(profile, sensitivity, n_layers)

    # the ROI sub-image (clamped like box_integrate) for column-by-column tracing
    sub = _roi_subimage(work, roi) if waviness else None
    interfaces, layers = _interfaces_and_layers(
        depth_pos, profile, peaks, sub, use_axis, pixel_size, fit_window, trace_window
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


def recompute_layers(
    img: np.ndarray,
    positions: list[float],
    *,
    axis: str = "y",
    roi: tuple[int, int, int, int] | None = None,
    reduce: str = "mean",
    pixel_size: float = 1.0,
    unit: str = "px",
    fit_window: int = 15,
    waviness: bool = False,
    trace_window: int = 10,
    destripe_fib: bool = False,
    destripe_strength: float = 1.0,
    destripe_cutoff: float = 4.0,
) -> LayerResult:
    """Re-measure layers from a user-edited interface list (Tier 3 #6).

    Skips auto-detection: each supplied depth ``position`` (profile pixels)
    is erf-refined and the layers between consecutive interfaces are
    recomputed. ``axis`` is explicit (editing assumes a known orientation).
    Out-of-range positions are dropped; duplicates within a pixel collapse.
    ``destripe_fib``/``reduce="median"`` mirror :func:`analyze_layers` so an
    edited result stays consistent with how it was first measured.
    """
    arr = np.asarray(img, dtype=np.float64)
    if arr.ndim != 2:
        raise ValueError("layer analysis needs a 2-D image")
    if axis not in ("x", "y"):
        raise ValueError("axis must be 'x' or 'y'")

    work = (
        destripe(arr, axis, cutoff=destripe_cutoff, strength=destripe_strength)
        if destripe_fib
        else arr
    )
    depth_pos, profile = cross_section_profile(work, roi, axis, reduce)
    n = profile.size
    idxs = np.array(
        sorted({int(round(p)) for p in positions if 0 <= round(p) < n}), dtype=int
    )
    sub = _roi_subimage(work, roi) if waviness else None
    interfaces, layers = _interfaces_and_layers(
        depth_pos, profile, idxs, sub, axis, pixel_size, fit_window, trace_window
    )
    orient = detect_growth_orientation(arr)
    return LayerResult(
        axis=axis,
        layers_horizontal=(axis == "y"),
        tilt_deg=orient.tilt_deg,
        coherence=orient.coherence,
        depth_pos=depth_pos,
        depth_profile=profile,
        interfaces=interfaces,
        layers=layers,
        pixel_size=pixel_size,
        unit=unit,
    )
