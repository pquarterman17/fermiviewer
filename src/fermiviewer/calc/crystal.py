"""Crystallography: electron wavelength, phase database, d-spacings.

Port of fermi-viewer's calcElectronWavelength.m + +calc/+crystal/
(phaseDatabase, dSpacing, planeSpacings). Lattice parameters and basis
positions are verbatim; centering extinction rules include the
R-centering OBVERSE rule (−h+k+l ≡ 0 mod 3) — calibrated, do not "fix".
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

__all__ = ["PHASES", "Phase", "Reflections", "d_spacing", "electron_wavelength",
           "plane_spacings"]

Basis = tuple[tuple[str, float, float, float], ...]


def electron_wavelength(kv: float | np.ndarray) -> float | np.ndarray:
    """Relativistic de Broglie wavelength in Ångströms (port, CODATA)."""
    h = 6.62607015e-34
    m = 9.1093837015e-31
    e = 1.602176634e-19
    c = 299792458.0
    v = np.asarray(kv, dtype=np.float64) * 1e3
    lam = h / np.sqrt(2 * m * e * v * (1 + (e * v) / (2 * m * c**2))) * 1e10
    return float(lam) if np.isscalar(kv) else lam


# ── basis builders (fractional coordinates, verbatim) ────────────────

def _fcc(s: str) -> Basis:
    return ((s, 0, 0, 0), (s, 0.5, 0.5, 0), (s, 0.5, 0, 0.5), (s, 0, 0.5, 0.5))


def _bcc(s: str) -> Basis:
    return ((s, 0, 0, 0), (s, 0.5, 0.5, 0.5))


def _diamond(s: str) -> Basis:
    return _fcc(s) + (
        (s, 0.25, 0.25, 0.25), (s, 0.75, 0.75, 0.25),
        (s, 0.75, 0.25, 0.75), (s, 0.25, 0.75, 0.75),
    )


def _zincblende(a: str, b: str) -> Basis:
    return _fcc(a) + (
        (b, 0.25, 0.25, 0.25), (b, 0.75, 0.75, 0.25),
        (b, 0.75, 0.25, 0.75), (b, 0.25, 0.75, 0.75),
    )


def _rocksalt(cat: str, an: str) -> Basis:
    return _fcc(cat) + (
        (an, 0.5, 0, 0), (an, 0, 0.5, 0), (an, 0, 0, 0.5), (an, 0.5, 0.5, 0.5),
    )


def _perovskite(a: str, b: str, x: str) -> Basis:
    return ((a, 0, 0, 0), (b, 0.5, 0.5, 0.5),
            (x, 0.5, 0.5, 0), (x, 0.5, 0, 0.5), (x, 0, 0.5, 0.5))


def _fluorite(cat: str, an: str) -> Basis:
    return _fcc(cat) + tuple(
        (an, x, y, z)
        for x, y, z in [(0.25, 0.25, 0.25), (0.75, 0.75, 0.25), (0.75, 0.25, 0.75),
                        (0.25, 0.75, 0.75), (0.25, 0.25, 0.75), (0.75, 0.75, 0.75),
                        (0.75, 0.25, 0.25), (0.25, 0.75, 0.25)]
    )


def _hcp(s: str) -> Basis:
    return ((s, 0, 0, 0), (s, 1 / 3, 2 / 3, 0.5))


def _wurtzite(a: str, b: str, u: float) -> Basis:
    return ((a, 1 / 3, 2 / 3, 0), (a, 2 / 3, 1 / 3, 0.5),
            (b, 1 / 3, 2 / 3, u), (b, 2 / 3, 1 / 3, 0.5 + u))


def _rutile(cat: str, an: str, u: float) -> Basis:
    return ((cat, 0, 0, 0), (cat, 0.5, 0.5, 0.5),
            (an, u, u, 0), (an, 1 - u, 1 - u, 0),
            (an, 0.5 + u, 0.5 - u, 0.5), (an, 0.5 - u, 0.5 + u, 0.5))


def _cuprite() -> Basis:
    return (("O", 0, 0, 0), ("O", 0.5, 0.5, 0.5),
            ("Cu", 0.25, 0.25, 0.25), ("Cu", 0.75, 0.75, 0.25),
            ("Cu", 0.75, 0.25, 0.75), ("Cu", 0.25, 0.75, 0.75))


def _lab6() -> Basis:
    x = 0.1993
    return (("La", 0, 0, 0),
            ("B", 0.5 + x, 0.5, 0.5), ("B", 0.5 - x, 0.5, 0.5),
            ("B", 0.5, 0.5 + x, 0.5), ("B", 0.5, 0.5 - x, 0.5),
            ("B", 0.5, 0.5, 0.5 + x), ("B", 0.5, 0.5, 0.5 - x))


@dataclass(frozen=True)
class Phase:
    name: str
    formula: str
    a: float
    b: float
    c: float
    alpha: float
    beta: float
    gamma: float
    centering: str
    system: str
    category: str
    icsd: int
    basis: Basis = field(default=())


def _p(
    name: str, formula: str, a: float, b: float, c: float,
    alpha: float, beta: float, gamma: float,
    centering: str, system: str, category: str, icsd: int,
    basis: Basis = (),
) -> Phase:
    return Phase(name, formula, a, b, c, alpha, beta, gamma,
                 centering, system, category, icsd, basis)


PHASES: tuple[Phase, ...] = (
    _p("Silicon", "Si", 5.4309, 5.4309, 5.4309, 90, 90, 90, "F", "cubic", "substrate", 51688, basis=_diamond("Si")),
    _p("Sapphire (Al2O3)", "Al2O3", 4.7589, 4.7589, 12.9910, 90, 90, 120, "R", "hexagonal", "substrate", 10425),
    _p("SrTiO3", "SrTiO3", 3.9050, 3.9050, 3.9050, 90, 90, 90, "P", "cubic", "substrate", 80871, basis=_perovskite("Sr", "Ti", "O")),
    _p("MgO", "MgO", 4.2112, 4.2112, 4.2112, 90, 90, 90, "F", "cubic", "substrate", 52026, basis=_rocksalt("Mg", "O")),
    _p("LaAlO3", "LaAlO3", 3.7900, 3.7900, 3.7900, 90, 90, 90, "P", "cubic", "substrate", 56941, basis=_perovskite("La", "Al", "O")),
    _p("GaAs", "GaAs", 5.6533, 5.6533, 5.6533, 90, 90, 90, "F", "cubic", "substrate", 41674, basis=_zincblende("Ga", "As")),
    _p("Ge", "Ge", 5.6576, 5.6576, 5.6576, 90, 90, 90, "F", "cubic", "substrate", 41980, basis=_diamond("Ge")),
    _p("GaN (wurtzite)", "GaN", 3.1890, 3.1890, 5.1864, 90, 90, 120, "P", "hexagonal", "substrate", 67782, basis=_wurtzite("Ga", "N", 0.376)),
    _p("TiO2 rutile", "TiO2", 4.5941, 4.5941, 2.9589, 90, 90, 90, "P", "tetragonal", "substrate", 44882, basis=_rutile("Ti", "O", 0.3051)),
    _p("SiC 4H", "SiC", 3.0730, 3.0730, 10.0530, 90, 90, 120, "P", "hexagonal", "substrate", 0),
    _p("Aluminum", "Al", 4.0495, 4.0495, 4.0495, 90, 90, 90, "F", "cubic", "metal", 64700, basis=_fcc("Al")),
    _p("Copper", "Cu", 3.6149, 3.6149, 3.6149, 90, 90, 90, "F", "cubic", "metal", 43493, basis=_fcc("Cu")),
    _p("Gold", "Au", 4.0782, 4.0782, 4.0782, 90, 90, 90, "F", "cubic", "metal", 44362, basis=_fcc("Au")),
    _p("Silver", "Ag", 4.0862, 4.0862, 4.0862, 90, 90, 90, "F", "cubic", "metal", 64706, basis=_fcc("Ag")),
    _p("Platinum", "Pt", 3.9231, 3.9231, 3.9231, 90, 90, 90, "F", "cubic", "metal", 64923, basis=_fcc("Pt")),
    _p("Palladium", "Pd", 3.8898, 3.8898, 3.8898, 90, 90, 90, "F", "cubic", "metal", 64918, basis=_fcc("Pd")),
    _p("Nickel", "Ni", 3.5238, 3.5238, 3.5238, 90, 90, 90, "F", "cubic", "metal", 64989, basis=_fcc("Ni")),
    _p("Iron (BCC)", "Fe", 2.8665, 2.8665, 2.8665, 90, 90, 90, "I", "cubic", "metal", 64795, basis=_bcc("Fe")),
    _p("Iron (FCC)", "Fe", 3.5910, 3.5910, 3.5910, 90, 90, 90, "F", "cubic", "metal", 44863, basis=_fcc("Fe")),
    _p("Tungsten", "W", 3.1648, 3.1648, 3.1648, 90, 90, 90, "I", "cubic", "metal", 43421, basis=_bcc("W")),
    _p("Chromium", "Cr", 2.8839, 2.8839, 2.8839, 90, 90, 90, "I", "cubic", "metal", 64711, basis=_bcc("Cr")),
    _p("Titanium (HCP)", "Ti", 2.9505, 2.9505, 4.6826, 90, 90, 120, "P", "hexagonal", "metal", 44872, basis=_hcp("Ti")),
    _p("Cobalt (HCP)", "Co", 2.5071, 2.5071, 4.0695, 90, 90, 120, "P", "hexagonal", "metal", 44989, basis=_hcp("Co")),
    _p("Molybdenum", "Mo", 3.1472, 3.1472, 3.1472, 90, 90, 90, "I", "cubic", "metal", 64915, basis=_bcc("Mo")),
    _p("Tantalum (BCC)", "Ta", 3.3013, 3.3013, 3.3013, 90, 90, 90, "I", "cubic", "metal", 64946, basis=_bcc("Ta")),
    _p("ZnO (wurtzite)", "ZnO", 3.2498, 3.2498, 5.2066, 90, 90, 120, "P", "hexagonal", "oxide", 67849, basis=_wurtzite("Zn", "O", 0.3826)),
    _p("Fe2O3 (hematite)", "Fe2O3", 5.0356, 5.0356, 13.7489, 90, 90, 120, "R", "hexagonal", "oxide", 82137),
    _p("Fe3O4 (magnetite)", "Fe3O4", 8.3941, 8.3941, 8.3941, 90, 90, 90, "F", "cubic", "oxide", 26410),
    _p("NiO", "NiO", 4.1771, 4.1771, 4.1771, 90, 90, 90, "F", "cubic", "oxide", 24018, basis=_rocksalt("Ni", "O")),
    _p("CoO", "CoO", 4.2612, 4.2612, 4.2612, 90, 90, 90, "F", "cubic", "oxide", 24019, basis=_rocksalt("Co", "O")),
    _p("CuO (tenorite)", "CuO", 4.6837, 3.4226, 5.1288, 90, 99.54, 90, "C", "monoclinic", "oxide", 16025),
    _p("Cu2O (cuprite)", "Cu2O", 4.2696, 4.2696, 4.2696, 90, 90, 90, "P", "cubic", "oxide", 63281, basis=_cuprite()),
    _p("TiO2 (anatase)", "TiO2", 3.7852, 3.7852, 9.5139, 90, 90, 90, "I", "tetragonal", "oxide", 44882),
    _p("SiO2 (quartz)", "SiO2", 4.9134, 4.9134, 5.4052, 90, 90, 120, "P", "hexagonal", "oxide", 16331),
    _p("SnO2 (cassiterite)", "SnO2", 4.7382, 4.7382, 3.1871, 90, 90, 90, "P", "tetragonal", "oxide", 39173, basis=_rutile("Sn", "O", 0.3056)),
    _p("In2O3 (bixbyite)", "In2O3", 10.1170, 10.1170, 10.1170, 90, 90, 90, "I", "cubic", "oxide", 14388),
    _p("Cr2O3 (eskolaite)", "Cr2O3", 4.9570, 4.9570, 13.5920, 90, 90, 120, "R", "hexagonal", "oxide", 25781),
    _p("BaTiO3", "BaTiO3", 3.9945, 3.9945, 4.0335, 90, 90, 90, "P", "tetragonal", "perovskite", 67520, basis=_perovskite("Ba", "Ti", "O")),
    _p("PbTiO3", "PbTiO3", 3.8990, 3.8990, 4.1530, 90, 90, 90, "P", "tetragonal", "perovskite", 0, basis=_perovskite("Pb", "Ti", "O")),
    _p("La0.7Sr0.3MnO3", "LSMO", 3.8760, 3.8760, 3.8760, 90, 90, 90, "P", "cubic", "perovskite", 0, basis=_perovskite("La", "Mn", "O")),
    _p("BiFeO3", "BiFeO3", 5.5876, 5.5876, 13.8670, 90, 90, 120, "R", "hexagonal", "perovskite", 15299),
    _p("LaNiO3", "LaNiO3", 3.8380, 3.8380, 3.8380, 90, 90, 90, "P", "cubic", "perovskite", 0, basis=_perovskite("La", "Ni", "O")),
    _p("SrRuO3", "SrRuO3", 5.5670, 5.5304, 7.8446, 90, 90, 90, "P", "orthorhombic", "perovskite", 0),
    _p("InAs", "InAs", 6.0583, 6.0583, 6.0583, 90, 90, 90, "F", "cubic", "semiconductor", 43479, basis=_zincblende("In", "As")),
    _p("InP", "InP", 5.8688, 5.8688, 5.8688, 90, 90, 90, "F", "cubic", "semiconductor", 41432, basis=_zincblende("In", "P")),
    _p("CdTe", "CdTe", 6.4810, 6.4810, 6.4810, 90, 90, 90, "F", "cubic", "semiconductor", 0, basis=_zincblende("Cd", "Te")),
    _p("ZnSe", "ZnSe", 5.6676, 5.6676, 5.6676, 90, 90, 90, "F", "cubic", "semiconductor", 0, basis=_zincblende("Zn", "Se")),
    _p("AlN (wurtzite)", "AlN", 3.1114, 3.1114, 4.9792, 90, 90, 120, "P", "hexagonal", "semiconductor", 0, basis=_wurtzite("Al", "N", 0.3821)),
    _p("LaB6 (standard)", "LaB6", 4.1569, 4.1569, 4.1569, 90, 90, 90, "P", "cubic", "other", 30450, basis=_lab6()),
    _p("CaF2 (fluorite)", "CaF2", 5.4626, 5.4626, 5.4626, 90, 90, 90, "F", "cubic", "other", 41413, basis=_fluorite("Ca", "F")),
    _p("NaCl (halite)", "NaCl", 5.6402, 5.6402, 5.6402, 90, 90, 90, "F", "cubic", "other", 18189, basis=_rocksalt("Na", "Cl")),
    _p("BN (hexagonal)", "BN", 2.5040, 2.5040, 6.6612, 90, 90, 120, "P", "hexagonal", "other", 0),
)


def find_phase(name: str) -> Phase:
    """Case-insensitive contains-match on phase name (MATLAB convention)."""
    needle = name.strip().lower()
    for p in PHASES:
        if needle in p.name.lower():
            return p
    raise KeyError(f"no phase matching '{name}'")


# ── d-spacing (general triclinic formula, port of dSpacing.m) ────────

def d_spacing(
    a: float, h: int, k: int, l: int,  # noqa: E741 — Miller index
    b: float | None = None, c: float | None = None,
    alpha: float = 90, beta: float = 90, gamma: float = 90,
) -> float:
    b = a if b is None else b
    c = a if c is None else c
    al, be, ga = np.deg2rad([alpha, beta, gamma])
    vol = a * b * c * np.sqrt(
        1 - np.cos(al) ** 2 - np.cos(be) ** 2 - np.cos(ga) ** 2
        + 2 * np.cos(al) * np.cos(be) * np.cos(ga)
    )
    inv_d2 = (
        h**2 * b**2 * c**2 * np.sin(al) ** 2
        + k**2 * a**2 * c**2 * np.sin(be) ** 2
        + l**2 * a**2 * b**2 * np.sin(ga) ** 2
        + 2 * h * k * a * b * c**2 * (np.cos(al) * np.cos(be) - np.cos(ga))
        + 2 * k * l * a**2 * b * c * (np.cos(be) * np.cos(ga) - np.cos(al))
        + 2 * h * l * a * b**2 * c * (np.cos(al) * np.cos(ga) - np.cos(be))
    ) / vol**2
    return float(1 / np.sqrt(inv_d2))


def _allowed(h: int, k: int, l: int, centering: str) -> bool:  # noqa: E741
    """Bravais extinction rules. R uses the OBVERSE setting −h+k+l ≡ 0 (3)."""
    match centering:
        case "F":
            par = [h % 2, k % 2, l % 2]
            return all(p == 0 for p in par) or all(p == 1 for p in par)
        case "I":
            return (h + k + l) % 2 == 0
        case "A":
            return (k + l) % 2 == 0
        case "B":
            return (h + l) % 2 == 0
        case "C":
            return (h + k) % 2 == 0
        case "R":
            return (-h + k + l) % 3 == 0
        case _:
            return True


@dataclass(frozen=True)
class Reflections:
    hkl: np.ndarray            # [n, 3] representative indices
    d: np.ndarray              # [n] Å, descending
    two_theta: np.ndarray      # [n] degrees (NaN beyond λ/2d limit)
    multiplicity: np.ndarray   # [n]
    centering: str


def plane_spacings(
    a: float,
    b: float | None = None, c: float | None = None,
    alpha: float = 90, beta: float = 90, gamma: float = 90,
    max_hkl: int = 5,
    lam: float = 1.5406,
    centering: str = "P",
    min_d: float = 0.0,
) -> Reflections:
    """Allowed reflections grouped by d (port of planeSpacings.m)."""
    centering = centering.upper()
    hkl_list: list[tuple[int, int, int]] = []
    d_list: list[float] = []
    rng = range(-max_hkl, max_hkl + 1)
    for hh in rng:
        for kk in rng:
            for ll in rng:
                if hh == kk == ll == 0 or not _allowed(hh, kk, ll, centering):
                    continue
                d = d_spacing(a, hh, kk, ll, b=b, c=c,
                              alpha=alpha, beta=beta, gamma=gamma)
                if d < min_d:
                    continue
                hkl_list.append((hh, kk, ll))
                d_list.append(d)

    hkl_arr = np.array(hkl_list)
    d_arr = np.array(d_list)

    # group by d rounded to 8 decimals, first-seen order (MATLAB 'stable')
    groups: dict[float, list[int]] = {}
    for i, dr in enumerate(np.round(d_arr, 8)):
        groups.setdefault(float(dr), []).append(i)

    reps, ds, mult = [], [], []
    for members in groups.values():
        m_hkl = hkl_arr[members]
        ds.append(d_arr[members].mean())
        mult.append(len(members))
        pos = (m_hkl[:, 0] > 0) | ((m_hkl[:, 0] == 0) & (m_hkl[:, 1] > 0)) | (
            (m_hkl[:, 0] == 0) & (m_hkl[:, 1] == 0) & (m_hkl[:, 2] > 0)
        )
        cand = m_hkl[pos] if pos.any() else m_hkl
        n_negs = (cand < 0).sum(axis=1)
        order = np.lexsort(
            (np.abs(cand[:, 2]), np.abs(cand[:, 1]), np.abs(cand[:, 0]),
             -cand.sum(axis=1), n_negs)
        )
        reps.append(cand[order[0]])

    d_out = np.array(ds)
    sort_idx = np.argsort(-d_out, kind="stable")
    d_out = d_out[sort_idx]
    hkl_out = np.array(reps)[sort_idx]
    mult_out = np.array(mult)[sort_idx]

    with np.errstate(invalid="ignore"):
        sin_t = lam / (2 * d_out)
        two_theta = 2 * np.degrees(np.arcsin(np.minimum(sin_t, 1.0)))
        two_theta[sin_t > 1] = np.nan

    return Reflections(hkl_out, d_out, two_theta, mult_out, centering)
