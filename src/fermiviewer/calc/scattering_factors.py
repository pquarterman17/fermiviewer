r"""Electron scattering factors (Doyle--Turner) and the Debye--Waller factor.

Pure-physics layer: numpy / stdlib only, no server stack. Provides the
real electron atomic scattering factor f_e(s) used to weight the
structure-factor sum in kinematic diffraction, replacing the crude
"atomic number Z as a proxy" approximation.

Theory
------
The electron scattering factor is parameterised as a sum of Gaussians in
the scattering parameter ``s = sin(theta) / lambda = 1 / (2 d)`` (units
A^-1):

.. math::

    f_e(s) = \sum_{i=1}^{N} a_i \, \exp(-b_i s^2)

with ``f_e`` in Angstroms and ``b_i`` in A^2. At ``s = 0`` the value
``f_e(0) = sum(a_i)`` is the forward-scattering amplitude, which grows
roughly with Z (heavier atoms scatter electrons more strongly) but is
NOT simply equal to Z -- the whole point of using real factors.

Thermal motion is folded in by the isotropic Debye--Waller factor:

.. math::

    \mathrm{DW}(s) = \exp(-B s^2)

where ``B = 8 pi^2 <u^2>`` is the isotropic atomic displacement
parameter (A^2). This damps high-``s`` (small-``d``) reflections far
more than low-``s`` ones, which is why high-order spots fade in a real
pattern.

Sources
-------
1. P. A. Doyle and P. S. Turner, "Relativistic Hartree-Fock X-ray and
   electron scattering factors", Acta Cryst. A24 (1968) 390-397. The
   four-Gaussian fit ``f_e(s) = sum_i a_i exp(-b_i s^2)`` reproduced
   here (also tabulated in International Tables for Crystallography
   Vol. C, Table 4.3.1.1, the "Doyle & Turner" columns). Valid for
   ``s`` in the range 0 to 2 A^-1.
2. Debye--Waller B values: room-temperature isotropic B (A^2)
   collected from L.-M. Peng, G. Ren, S. L. Dudarev and M. J. Whelan,
   "Debye-Waller factors and absorptive scattering factors of
   elemental crystals", Acta Cryst. A52 (1996) 456-470, supplemented by
   common values from International Tables Vol. C. These are coarse
   room-temperature defaults intended for qualitative damping of high-s
   reflections; pass an explicit ``B`` for quantitative work.

The coefficient tables below are transcribed numeric data, not code.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.crystal import Basis
from fermiviewer.calc.elements import atomic_number

__all__ = [
    "DOYLE_TURNER",
    "BasisModel",
    "build_basis_model",
    "debye_waller",
    "default_debye_waller_B",
    "electron_scattering_factor",
    "has_scattering_factor",
    "reflection_intensity",
    "scattering_weight",
]


# ════════════════════════════════════════════════════════════════════
# Doyle--Turner four-Gaussian coefficients
#   value = (a1, b1, a2, b2, a3, b3, a4, b4)
#   f_e(s) = sum_i a_i exp(-b_i s^2),  s = sin(theta)/lambda [A^-1]
#   a_i in A, b_i in A^2.  Source: Doyle & Turner, Acta Cryst. A24 (1968)
#   390; reproduced in Int. Tables Vol. C, Table 4.3.1.1.
# ════════════════════════════════════════════════════════════════════

DOYLE_TURNER: dict[str, tuple[float, float, float, float, float, float, float, float]] = {
    "H":  (0.202, 30.868, 0.244, 8.544, 0.082, 1.273, 0.000, 0.000),
    "He": (0.091, 18.183, 0.181, 6.212, 0.110, 1.803, 0.036, 0.284),
    "Li": (1.611, 107.638, 1.246, 30.480, 0.326, 4.533, 0.099, 0.495),
    "Be": (1.250, 60.804, 1.334, 18.591, 0.360, 3.653, 0.106, 0.416),
    "B":  (0.945, 46.444, 1.312, 14.178, 0.419, 3.223, 0.116, 0.377),
    "C":  (0.731, 36.995, 1.195, 11.297, 0.456, 2.814, 0.125, 0.346),
    "N":  (0.572, 28.847, 1.043, 9.054, 0.465, 2.421, 0.131, 0.317),
    "O":  (0.455, 23.780, 0.917, 7.622, 0.472, 2.144, 0.138, 0.296),
    "F":  (0.387, 20.239, 0.811, 6.609, 0.475, 1.931, 0.146, 0.279),
    "Ne": (0.303, 17.640, 0.720, 5.860, 0.475, 1.762, 0.153, 0.266),
    "Na": (2.241, 108.004, 1.333, 24.505, 0.907, 3.391, 0.286, 0.435),
    "Mg": (2.268, 73.670, 1.803, 20.175, 0.839, 3.013, 0.289, 0.405),
    "Al": (2.276, 72.322, 2.428, 19.773, 0.858, 3.080, 0.317, 0.408),
    "Si": (2.129, 57.775, 2.533, 16.476, 0.835, 2.880, 0.322, 0.386),
    "P":  (1.888, 44.876, 2.469, 13.538, 0.805, 2.642, 0.320, 0.361),
    "S":  (1.659, 36.650, 2.386, 11.488, 0.790, 2.469, 0.321, 0.340),
    "Cl": (1.452, 30.935, 2.292, 9.980, 0.787, 2.234, 0.322, 0.323),
    "Ar": (1.274, 26.682, 2.190, 8.813, 0.793, 2.219, 0.326, 0.307),
    "K":  (3.951, 137.075, 2.545, 22.402, 1.980, 4.532, 0.482, 0.434),
    "Ca": (4.470, 99.523, 2.971, 22.696, 1.970, 4.195, 0.482, 0.417),
    "Sc": (3.966, 88.960, 2.917, 20.606, 1.925, 3.856, 0.480, 0.399),
    "Ti": (3.565, 81.982, 2.818, 19.049, 1.893, 3.590, 0.483, 0.386),
    "V":  (3.245, 76.379, 2.698, 17.726, 1.860, 3.363, 0.486, 0.374),
    "Cr": (2.307, 78.405, 2.334, 15.785, 1.823, 3.157, 0.490, 0.364),
    "Mn": (2.747, 67.786, 2.456, 15.674, 1.792, 3.000, 0.498, 0.357),
    "Fe": (2.544, 64.424, 2.343, 14.880, 1.759, 2.854, 0.506, 0.350),
    "Co": (2.367, 61.431, 2.236, 14.180, 1.724, 2.725, 0.515, 0.344),
    "Ni": (2.210, 58.727, 2.134, 13.553, 1.689, 2.609, 0.524, 0.339),
    "Cu": (1.579, 62.940, 1.820, 12.453, 1.658, 2.504, 0.532, 0.333),
    "Zn": (1.942, 54.162, 1.950, 12.518, 1.619, 2.416, 0.543, 0.330),
    "Ga": (2.321, 65.602, 2.486, 15.458, 1.688, 2.581, 0.599, 0.351),
    "Ge": (2.447, 55.893, 2.702, 14.393, 1.616, 2.446, 0.601, 0.342),
    "As": (2.399, 45.718, 2.790, 12.817, 1.529, 2.280, 0.594, 0.328),
    "Se": (2.298, 38.830, 2.854, 11.536, 1.456, 2.146, 0.590, 0.316),
    "Br": (2.166, 33.899, 2.904, 10.497, 1.395, 2.041, 0.589, 0.307),
    "Kr": (2.034, 29.999, 2.927, 9.598, 1.342, 1.952, 0.589, 0.299),
    "Rb": (4.776, 140.782, 3.859, 18.991, 2.234, 3.701, 0.868, 0.419),
    "Sr": (5.848, 104.972, 4.003, 19.367, 2.342, 3.737, 0.880, 0.414),
    "Y":  (4.129, 27.548, 3.012, 5.088, 1.179, 0.591, 0.000, 0.000),
    "Zr": (4.105, 28.492, 3.144, 5.277, 1.229, 0.601, 0.000, 0.000),
    "Nb": (4.237, 27.415, 3.105, 5.074, 1.234, 0.593, 0.000, 0.000),
    "Mo": (3.120, 72.464, 3.906, 14.642, 2.361, 3.237, 0.850, 0.366),
    "Ru": (3.894, 25.044, 3.135, 4.853, 1.278, 0.568, 0.000, 0.000),
    "Rh": (3.854, 24.521, 3.143, 4.802, 1.297, 0.566, 0.000, 0.000),
    "Pd": (4.105, 28.492, 3.144, 5.277, 1.229, 0.601, 0.000, 0.000),
    "Ag": (2.036, 61.497, 3.272, 11.824, 2.511, 2.846, 0.837, 0.327),
    "Cd": (2.574, 55.675, 3.259, 11.838, 2.547, 2.784, 0.838, 0.322),
    "In": (3.153, 66.649, 3.557, 14.449, 2.818, 2.976, 0.884, 0.335),
    "Sn": (3.450, 59.104, 3.735, 14.179, 2.118, 2.855, 0.877, 0.327),
    "Sb": (3.564, 50.487, 3.844, 13.316, 2.687, 2.691, 0.864, 0.316),
    "Te": (4.785, 27.999, 3.688, 5.083, 1.500, 0.581, 0.000, 0.000),
    "I":  (3.473, 39.441, 4.060, 11.816, 2.522, 2.415, 0.840, 0.298),
    "Xe": (3.366, 35.509, 4.147, 11.117, 2.443, 2.294, 0.829, 0.289),
    "Cs": (6.062, 155.837, 5.986, 19.695, 3.303, 3.335, 1.096, 0.379),
    "Ba": (7.821, 117.657, 6.004, 18.778, 3.280, 3.263, 1.103, 0.376),
    "La": (4.940, 28.716, 3.968, 5.245, 1.663, 0.594, 0.000, 0.000),
    "Ce": (5.007, 28.283, 3.980, 5.183, 1.678, 0.589, 0.000, 0.000),
    "Ta": (5.659, 28.807, 4.630, 5.114, 2.748, 0.555, 0.000, 0.000),
    "W":  (5.709, 28.782, 4.677, 5.084, 2.755, 0.550, 0.000, 0.000),
    "Pt": (5.803, 29.016, 4.870, 5.150, 2.844, 0.531, 0.000, 0.000),
    "Au": (2.388, 42.866, 4.226, 9.743, 2.689, 2.264, 1.255, 0.307),
    "Hg": (2.682, 42.822, 4.241, 9.856, 2.755, 2.295, 1.270, 0.307),
    "Pb": (3.510, 52.914, 4.552, 11.884, 3.154, 2.571, 1.359, 0.321),
    "Bi": (3.841, 50.261, 4.679, 11.999, 3.192, 2.560, 1.363, 0.318),
    "Th": (6.264, 28.651, 4.860, 5.369, 3.040, 0.571, 0.000, 0.000),
    "U":  (6.767, 85.951, 6.729, 15.642, 4.014, 2.936, 1.561, 0.335),
}


def has_scattering_factor(element: str) -> bool:
    """Return True if a Doyle--Turner fit is tabulated for *element*."""
    return element in DOYLE_TURNER


def electron_scattering_factor(
    element: str,
    s: float | np.ndarray,
) -> np.ndarray:
    r"""Electron atomic scattering factor f_e(s) (Doyle--Turner).

    Evaluates ``f_e(s) = sum_i a_i exp(-b_i s^2)`` (Angstroms) for the
    given chemical *element* at scattering parameter ``s = sin(theta)/lambda
    = 1/(2 d)`` in A^-1.

    Args:
        element: chemical symbol, e.g. ``"Si"``, ``"Au"``. Case-sensitive
            (matches the periodic-table convention used throughout this
            package).
        s: scattering parameter ``sin(theta)/lambda`` in A^-1. Scalar or
            ndarray; the return shape matches.

    Returns:
        f_e(s) in Angstroms, as a float64 ndarray (0-d for scalar input).

    Raises:
        KeyError: if no Doyle--Turner fit is tabulated for *element*.

    Reference:
        Doyle & Turner, Acta Cryst. A24 (1968) 390; Int. Tables Vol. C
        Table 4.3.1.1. Valid for s in [0, 2] A^-1.

    Example:
        >>> round(float(electron_scattering_factor("Si", 0.0)), 3)
        5.819
        >>> # monotonically decreasing
        >>> bool(electron_scattering_factor("Si", 0.0)
        ...      > electron_scattering_factor("Si", 0.3))
        True
    """
    if element not in DOYLE_TURNER:
        raise KeyError(
            f"no Doyle-Turner electron scattering factor tabulated for "
            f"'{element}'; covered elements: {sorted(DOYLE_TURNER)}"
        )
    a1, b1, a2, b2, a3, b3, a4, b4 = DOYLE_TURNER[element]
    s_arr = np.asarray(s, dtype=np.float64)
    s2 = s_arr * s_arr
    fe = (
        a1 * np.exp(-b1 * s2)
        + a2 * np.exp(-b2 * s2)
        + a3 * np.exp(-b3 * s2)
        + a4 * np.exp(-b4 * s2)
    )
    return np.asarray(fe, dtype=np.float64)


# ════════════════════════════════════════════════════════════════════
# Debye--Waller factor
#   Room-temperature isotropic B (A^2). Coarse defaults for qualitative
#   high-s damping; pass an explicit B for quantitative work.
#   Source: Peng, Ren, Dudarev & Whelan, Acta Cryst. A52 (1996) 456
#   (elemental crystals at 293 K), supplemented by Int. Tables Vol. C.
# ════════════════════════════════════════════════════════════════════

_DEFAULT_B: dict[str, float] = {
    "C": 0.20,   # diamond
    "Al": 0.85,
    "Si": 0.46,
    "Ti": 0.50,
    "Cr": 0.27,
    "Fe": 0.35,
    "Co": 0.35,
    "Ni": 0.35,
    "Cu": 0.55,
    "Zn": 0.85,
    "Ga": 0.78,
    "Ge": 0.57,
    "As": 0.55,
    "Mo": 0.21,
    "Pd": 0.45,
    "Ag": 0.65,
    "Sn": 0.95,
    "Ta": 0.20,
    "W": 0.18,
    "Pt": 0.27,
    "Au": 0.58,
    "Pb": 2.10,
    "Mg": 0.85,
    "Sr": 0.90,
    "O": 0.50,
    "N": 0.50,
}

# Coarse fallback B (A^2) for elements without a tabulated value: a
# typical room-temperature solid value. Documented as a default, not a
# measurement.
_FALLBACK_B = 0.50


def default_debye_waller_B(element: str) -> float:  # noqa: N802 — B is the physics symbol
    """Room-temperature isotropic Debye--Waller B (A^2) for *element*.

    Coarse 293 K values for qualitative high-s damping; falls back to a
    generic 0.5 A^2 for elements without a tabulated entry. Pass an
    explicit ``B`` to ``debye_waller`` for quantitative work.

    Reference:
        Peng, Ren, Dudarev & Whelan, Acta Cryst. A52 (1996) 456;
        Int. Tables Vol. C.
    """
    return _DEFAULT_B.get(element, _FALLBACK_B)


def debye_waller(
    s: float | np.ndarray,
    B: float | np.ndarray,  # noqa: N803 — B is the physics symbol
) -> np.ndarray:
    r"""Isotropic Debye--Waller factor ``exp(-B s^2)``.

    Damps the scattering amplitude due to thermal vibration. ``B = 8
    pi^2 <u^2>`` is the isotropic atomic displacement parameter (A^2);
    ``s = sin(theta)/lambda = 1/(2 d)`` (A^-1). High-``s`` (small-``d``)
    reflections are suppressed far more than low-``s`` ones.

    ``s`` and ``B`` broadcast against each other, so a scalar ``s`` with
    a per-atom ``B`` array returns one DW factor per atom.

    Args:
        s: scattering parameter in A^-1 (scalar or ndarray).
        B: isotropic displacement parameter in A^2 (>= 0), scalar or
            ndarray. ``B = 0`` disables damping (returns all ones).

    Returns:
        ``exp(-B s^2)`` as a float64 ndarray (0-d for scalar input). In
        the range (0, 1]; 1 at s=0, decreasing with s.

    Reference:
        Standard isotropic Debye--Waller form, e.g. Int. Tables Vol. C
        §4.3.

    Example:
        >>> float(debye_waller(0.0, 0.5))
        1.0
        >>> bool(debye_waller(0.5, 0.5) < debye_waller(0.1, 0.5))
        True
    """
    s_arr = np.asarray(s, dtype=np.float64)
    b_arr = np.asarray(B, dtype=np.float64)
    return np.asarray(np.exp(-b_arr * s_arr * s_arr), dtype=np.float64)


def scattering_weight(
    element: str,
    s: float | np.ndarray,
    model: str = "fe",
) -> np.ndarray:
    """Per-atom scattering weight for the structure-factor sum.

    Dispatches between the real Doyle--Turner electron scattering factor
    (``model="fe"``) and the legacy atomic-number proxy (``model="z"``,
    pinned so the simulate golden does not move). Returns an ndarray
    broadcast to the shape of *s*.

    Args:
        element: chemical symbol.
        s: scattering parameter sin(theta)/lambda in A^-1.
        model: ``"fe"`` (Doyle--Turner) or ``"z"`` (atomic-number proxy).

    Raises:
        ValueError: for an unknown *model*.
        KeyError: ``model="fe"`` with an un-tabulated element.
    """
    if model == "fe":
        return electron_scattering_factor(element, s)
    if model == "z":
        z = float(atomic_number(element))
        return np.broadcast_to(np.float64(z), np.shape(np.asarray(s))).astype(
            np.float64
        )
    raise ValueError(f"unknown scattering_model '{model}' (expected 'fe' or 'z')")


# ════════════════════════════════════════════════════════════════════
# Structure factor from an atomic basis
#   |F(hkl)|^2 = | sum_j w_j exp(2πi (h x_j + k y_j + l z_j)) |^2
#   with per-atom weight w_j = scattering_weight(...) optionally damped
#   by the Debye--Waller factor.
# ════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class BasisModel:
    """Precomputed per-atom data for the structure-factor sum.

    Attributes:
        symbols: element symbol per basis atom.
        frac: [n, 3] fractional coordinates.
        z: [n] atomic numbers (the legacy "z" proxy weight).
        b: [n] Debye--Waller B (A^2) per atom, or None when damping is off.
    """

    symbols: list[str]
    frac: np.ndarray
    z: np.ndarray
    b: np.ndarray | None


def build_basis_model(
    basis: Basis,
    debye_waller_b: float | None = None,
) -> BasisModel:
    """Precompute per-atom arrays for repeated structure-factor sums.

    Args:
        basis: tuple of ``(element, x, y, z)`` fractional-coordinate atoms
            (the ``Phase.basis`` contract).
        debye_waller_b: ``None`` (default) → no thermal damping; a float
            B in A^2 → one isotropic B for every atom; the sentinel
            ``-1.0`` → per-element room-temperature defaults
            (``default_debye_waller_B``).

    Returns:
        A frozen ``BasisModel``.
    """
    symbols = [sym for sym, *_ in basis]
    z = np.array([atomic_number(s) for s in symbols], dtype=np.float64)
    frac = np.array([[x, y, z_] for _, x, y, z_ in basis])
    if debye_waller_b is None:
        b: np.ndarray | None = None
    elif debye_waller_b < 0:                    # sentinel → per-element defaults
        b = np.array([default_debye_waller_B(s) for s in symbols], dtype=np.float64)
    else:
        b = np.full(len(symbols), float(debye_waller_b), dtype=np.float64)
    return BasisModel(symbols, frac, z, b)


def reflection_intensity(
    bm: BasisModel,
    hkl: tuple[int, int, int],
    s_hkl: float,
    model: str = "fe",
) -> float:
    r"""Kinematic |F(hkl)|^2 from an atomic basis at scattering parameter s.

    .. math::

        |F|^2 = \left| \sum_j w_j(s) \, e^{2\pi i (h x_j + k y_j + l z_j)}
                \right|^2

    where ``w_j`` is the per-atom scattering weight (Doyle--Turner
    ``f_e(s)`` for ``model="fe"`` or the atomic number for ``model="z"``),
    optionally multiplied by the Debye--Waller factor when ``bm.b`` is set.

    Args:
        bm: precomputed ``BasisModel``.
        hkl: Miller indices.
        s_hkl: scattering parameter ``sin(theta)/lambda = 1/(2 d) = |g|/2``
            (A^-1) for this reflection.
        model: ``"fe"`` (Doyle--Turner) or ``"z"`` (atomic-number proxy).

    Returns:
        The (real) intensity |F|^2 as a float.
    """
    if model == "z":
        weights = bm.z
    else:
        weights = np.array(
            [scattering_weight(sym, s_hkl, model) for sym in bm.symbols],
            dtype=np.float64,
        )
    if bm.b is not None:                        # per-atom DW: exp(-B_j s²)
        weights = weights * debye_waller(s_hkl, bm.b)
    ph = 2 * np.pi * (bm.frac @ hkl)
    f_hkl = (weights * np.exp(1j * ph)).sum()
    return float((f_hkl * np.conj(f_hkl)).real)
