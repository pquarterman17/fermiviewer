"""EELS core analysis: edge table, background subtraction, elemental maps,
thickness. Port of fermi-viewer's +imaging/+eels/ (core half).

Pure library (numpy only).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = [
    "EELS_EDGES",
    "Edge",
    "background",
    "extract_map",
    "thickness_map",
]

_EPS = np.finfo(np.float64).eps


@dataclass(frozen=True)
class Edge:
    element: str
    edge: str
    onset_ev: float
    z: int

    @property
    def symbol(self) -> str:
        return f"{self.element}-{self.edge}"


# Verbatim port of eelsEdgeTable.m — onset energies in eV.
EELS_EDGES: tuple[Edge, ...] = tuple(
    Edge(el, ed, float(on), z)
    for el, ed, on, z in [
        ("Li", "K", 55, 3), ("B", "K", 188, 5), ("C", "K", 284, 6),
        ("N", "K", 401, 7), ("O", "K", 532, 8), ("F", "K", 685, 9),
        ("Na", "K", 1072, 11), ("Mg", "K", 1305, 12), ("Al", "L23", 73, 13),
        ("Al", "K", 1560, 13), ("Si", "L23", 99, 14), ("Si", "K", 1839, 14),
        ("P", "L23", 135, 15), ("S", "L23", 165, 16), ("Cl", "L23", 200, 17),
        ("Ar", "L23", 245, 18), ("K", "L23", 294, 19), ("Ca", "L23", 346, 20),
        ("Sc", "L23", 397, 21), ("Ti", "L23", 456, 22), ("V", "L23", 513, 23),
        ("Cr", "L23", 575, 24), ("Mn", "L23", 640, 25), ("Fe", "L23", 708, 26),
        ("Co", "L23", 778, 27), ("Ni", "L23", 855, 28), ("Cu", "L23", 931, 29),
        ("Zn", "L23", 1020, 30), ("Ga", "L23", 1115, 31), ("Ge", "L23", 1217, 32),
        ("As", "L23", 1323, 33), ("Se", "L23", 1436, 34), ("Br", "L23", 1550, 35),
        ("Y", "L23", 2080, 39), ("Zr", "L23", 2222, 40), ("Nb", "M45", 205, 41),
        ("Mo", "M45", 227, 42), ("Ru", "M45", 279, 44), ("Pd", "M45", 335, 46),
        ("Ag", "M45", 367, 47), ("Sn", "M45", 485, 50), ("Sb", "M45", 528, 51),
        ("Ba", "M45", 781, 56), ("La", "M45", 832, 57), ("Ce", "M45", 883, 58),
        ("Sr", "L23", 1940, 38), ("W", "M45", 1809, 74), ("Pt", "M45", 2122, 78),
        ("Au", "M45", 2206, 79),
    ]
)


def _fit_window_mask(
    energy: np.ndarray, window: tuple[float, float] | None
) -> tuple[np.ndarray, tuple[float, float]]:
    if window is None:
        e0, e1 = float(energy.min()), float(energy.max())
        window = (e0, e0 + 0.2 * (e1 - e0))
    mask = (energy >= window[0]) & (energy <= window[1])
    if mask.sum() < 2:
        raise ValueError(
            f"fit window [{window[0]:.1f}, {window[1]:.1f}] eV has < 2 channels"
        )
    return mask, window


def background(
    energy: np.ndarray,
    spectrum: np.ndarray,
    fit_window: tuple[float, float] | None = None,
    method: str = "powerlaw",
) -> tuple[np.ndarray, np.ndarray, dict[str, float]]:
    """Pre-edge background fit + subtraction (port of eelsBackground.m).

    Returns (signal, background, params): powerlaw I = A·E^−r fitted in
    log-log; exponential I = A·exp(b·E) in log-linear. Negative residuals
    clamp to 0.
    """
    energy = np.asarray(energy, dtype=np.float64).ravel()
    spectrum = np.asarray(spectrum, dtype=np.float64).ravel()
    if energy.size != spectrum.size:
        raise ValueError("energy and spectrum must have equal length")

    mask, _ = _fit_window_mask(energy, fit_window)
    i_fit = np.maximum(spectrum[mask], _EPS)

    if method == "powerlaw":
        slope, intercept = np.polyfit(np.log(np.maximum(energy[mask], _EPS)),
                                      np.log(i_fit), 1)
        a, r = float(np.exp(intercept)), float(-slope)
        bg = a * np.maximum(energy, _EPS) ** (-r)
        params = {"A": a, "r": r}
    elif method == "exponential":
        b, intercept = np.polyfit(energy[mask], np.log(i_fit), 1)
        a = float(np.exp(intercept))
        bg = a * np.exp(b * energy)
        params = {"A": a, "b": float(b)}
    else:
        raise ValueError("method must be 'powerlaw' or 'exponential'")

    signal = np.maximum(spectrum - bg, 0.0)
    return signal, bg, params


def extract_map(
    cube: np.ndarray,
    energy: np.ndarray,
    signal_window: tuple[float, float],
    background_window: tuple[float, float] | None = None,
    method: str = "powerlaw",
) -> np.ndarray:
    """Elemental intensity map from an SI cube (port of eelsExtractMap.m).

    Vectorized per-pixel pre-edge fit via a single least-squares solve;
    without background_window the signal window is summed directly.
    """
    cube = np.asarray(cube, dtype=np.float64)
    energy = np.asarray(energy, dtype=np.float64).ravel()
    ny, nx, ne = cube.shape
    if energy.size != ne:
        raise ValueError("energy length must match cube channels")

    sig_mask = (energy >= signal_window[0]) & (energy <= signal_window[1])
    if not sig_mask.any():
        raise ValueError("signal window contains no channels")

    if background_window is None:
        direct: np.ndarray = cube[:, :, sig_mask].sum(axis=2)
        return direct

    fit_mask, _ = _fit_window_mask(energy, background_window)
    spec = cube.reshape(ny * nx, ne).T                     # [nE, Np]
    i_fit = np.maximum(spec[fit_mask], _EPS)               # [K, Np]
    e_sig = np.maximum(energy[sig_mask], _EPS)[:, None]    # [Ks, 1]

    if method == "powerlaw":
        x = np.log(np.maximum(energy[fit_mask], _EPS))
        design = np.column_stack([x, np.ones_like(x)])
        coeffs, *_ = np.linalg.lstsq(design, np.log(i_fit), rcond=None)
        a = np.exp(coeffs[1])                              # [Np]
        r = -coeffs[0]
        with np.errstate(over="ignore"):                   # noisy-pixel fits can
            bg_sig = e_sig ** (-r) * a                     # overflow → inf → clamp
    elif method == "exponential":
        x = energy[fit_mask]
        design = np.column_stack([x, np.ones_like(x)])
        coeffs, *_ = np.linalg.lstsq(design, np.log(i_fit), rcond=None)
        bg_sig = np.exp(e_sig * coeffs[0]) * np.exp(coeffs[1])
    else:
        raise ValueError("method must be 'powerlaw' or 'exponential'")

    resid = np.maximum(spec[sig_mask] - bg_sig, 0.0)
    resid[~np.isfinite(resid)] = 0.0
    out: np.ndarray = resid.sum(axis=0).reshape(ny, nx)
    return out


def thickness_map(
    cube: np.ndarray,
    energy: np.ndarray,
    zlp_window: tuple[float, float] = (-5.0, 5.0),
    min_counts: float = 100.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Log-ratio relative thickness t/λ map (port of eelsThicknessMap.m).

    Returns (t_over_lambda [Ny,Nx] with NaN where invalid, valid_mask).
    """
    cube = np.asarray(cube, dtype=np.float64)
    energy = np.asarray(energy, dtype=np.float64).ravel()
    ny, nx, ne = cube.shape
    if energy.size != ne:
        raise ValueError("energy length must match cube channels")
    zlp_mask = (energy >= zlp_window[0]) & (energy <= zlp_window[1])
    if not zlp_mask.any():
        raise ValueError("ZLP window contains no channels")

    i_total = cube.sum(axis=2)
    i_zlp = cube[:, :, zlp_mask].sum(axis=2)
    valid = (i_total >= min_counts) & (i_zlp > 0) & (i_total > i_zlp)

    t = np.full((ny, nx), np.nan)
    t[valid] = np.log(i_total[valid] / i_zlp[valid])
    return t, valid
