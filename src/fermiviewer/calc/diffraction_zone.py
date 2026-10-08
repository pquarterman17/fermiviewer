"""Zone-axis (spot-pattern) indexing: d-spacings AND the angles between spots.

`index_spots`' d-only pass matches every spot to its nearest ring on its own,
so phases with similar plane spacings tie, and the "zone axis" it reports is
whatever fits the family-representative hkls (Silicon [001] came out as
[-100]). A single-crystal spot pattern carries far more information: all its
spots are integer combinations of two basis vectors of one reciprocal-lattice
plane. This module uses that.

For each phase: take two short, non-collinear measured spots as a basis, try
every pair of allowed reflections whose d-spacings AND inter-spot angle agree
with them, express every other spot in that basis and check that the implied
reciprocal vector lands on an allowed (h, k, l). The best assignment gives a
consistent, signed hkl per spot and the zone axis [uvw] = g1 × g2 (Weiss zone
law), for any crystal system.

A fit is scored by the spots it explains, discounted by strong in-zone
reflections it predicts INSIDE the observed region that are not there, so
a partial pattern (ROI, one side of the pattern, beam stop) is not
penalised for what it could never show. Ties between equally good fits go
to the smaller length/angle error plus a small prior for low-index zones
(operators tilt to low-index zones; a high-index zone of a big cell can
fit any 2-D lattice to within a few percent).

Pure numpy; no MATLAB counterpart (the reference indexes by d only).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from math import ceil

import numpy as np
from scipy.spatial import Delaunay, QhullError

from fermiviewer.calc.crystal import Phase, lattice_bases
from fermiviewer.calc.scattering_factors import (
    electron_scattering_factor,
    has_scattering_factor,
)

__all__ = ["ZoneFit", "fit_zone", "measured_vectors", "rerank_by_zone"]

#: angle mismatch allowed between a measured spot pair and a reflection pair
ANGLE_TOL_DEG = 3.0
#: how many distinct basis pairs (shortest non-collinear first) to try per
#: phase, so a spurious spot in the basis does not sink the right phase
_MAX_BASES = 4
#: kinematic |F|² (relative to the strongest reflection) above which an
#: in-zone reflection is expected to show up as a spot
_VISIBLE = 0.01
#: residual added per doubling of the zone's real-space repeat |uvw·[a b c]|
#: over the cell's mean edge V^(1/3): decides between otherwise equal fits
_ZONE_PRIOR = 0.003
#: never enumerate indices beyond this, however large the cell
_MAX_INDEX = 30
#: and never more reflections than this per phase (hkl grid points)
_MAX_TABLE = 40_000
#: spots beyond |g| = 3 Å⁻¹ (d < 0.33 Å) are no electron-diffraction
#: reflection: the calibration is off, and a zone fit would only be noise
_MAX_G = 3.0


@dataclass(frozen=True)
class ZoneFit:
    """One phase's best self-consistent spot assignment."""

    matched_idx: np.ndarray       # indices into the input spots
    matched_hkl: np.ndarray       # (n, 3) signed integer hkl per matched spot
    ref_d: np.ndarray             # d of each assigned reflection (Å)
    zone_axis: tuple[float, float, float]
    residual: float               # d error + angle error + zone-index prior
    n_missing: int                # strong in-zone reflections with no spot
    score: float                  # matched / (valid spots + missing)


@dataclass(frozen=True)
class _Tables:
    hkl: np.ndarray               # (n, 3) allowed, nonzero reflections
    g: np.ndarray                 # (n, 3) Cartesian reciprocal vectors
    g_len: np.ndarray             # (n,) |g| = 1/d
    visible: np.ndarray           # (n,) strong enough to be seen
    key: np.ndarray               # (n,) integer code of each hkl (_code)
    grid: np.ndarray              # allowed[h+H0, k+H1, l+H2]
    span: tuple[int, int, int]    # (H0, H1, H2)
    direct: np.ndarray
    recip: np.ndarray
    a_mean: float                 # V^(1/3), the cell's mean edge (Å)


def _centering_ok(h: np.ndarray, k: np.ndarray, l: np.ndarray,  # noqa: E741
                  centering: str) -> np.ndarray:
    """Vectorised Bravais extinctions (same rules as crystal._allowed)."""
    return np.asarray(_centering_rule(h, k, l, centering), dtype=bool)


def _centering_rule(h, k, l, centering: str):  # noqa: ANN001, ANN202, E741
    match centering:
        case "F":
            return ((h + k) % 2 == 0) & ((h + l) % 2 == 0)
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
            return np.ones(h.shape, dtype=bool)


def _code(hkl: np.ndarray, span: tuple[int, int, int]) -> np.ndarray:
    n1, n2 = 2 * span[1] + 1, 2 * span[2] + 1
    code = ((hkl[:, 0] + span[0]) * n1 + hkl[:, 1] + span[1]) * n2 + hkl[:, 2] + span[2]
    return np.asarray(code, dtype=np.int64)


@lru_cache(maxsize=512)
def _tables(ph: Phase, span: tuple[int, int, int]) -> _Tables:
    """Every lattice-allowed reflection with |h| <= span[0] etc., cached per
    phase and span: indexing re-runs on every ROI drag against the whole
    phase database."""
    direct, recip = lattice_bases(ph)
    h, k, l = np.meshgrid(*(np.arange(-n, n + 1) for n in span),  # noqa: E741
                          indexing="ij")
    grid = _centering_ok(h, k, l, ph.centering.upper())
    grid[span] = False                                   # (0, 0, 0)
    hkl = np.column_stack([h[grid], k[grid], l[grid]])
    g = hkl @ recip
    g_len = np.linalg.norm(g, axis=1)
    return _Tables(hkl, g, g_len, _visible(ph, hkl, g_len), _code(hkl, span),
                   grid, span, direct, recip,
                   float(abs(np.linalg.det(direct))) ** (1 / 3))


def _visible(ph: Phase, hkl: np.ndarray, g_len: np.ndarray) -> np.ndarray:
    """Which allowed reflections are kinematically strong enough to see:
    |F|² from the atomic basis (Doyle-Turner f_e at s = |g|/2) when the
    phase has one — so e.g. Si 200, diamond-glide extinct, is not expected —
    else all centering-allowed ones."""
    flat = np.ones(len(hkl), dtype=bool)
    if not ph.basis or not all(has_scattering_factor(a[0]) for a in ph.basis):
        return flat
    frac = np.array([a[1:] for a in ph.basis], dtype=np.float64)
    s = g_len / 2.0
    w = np.column_stack([electron_scattering_factor(a[0], s) for a in ph.basis])
    f = (w * np.exp(2j * np.pi * (hkl @ frac.T))).sum(axis=1)
    inten = (f * f.conj()).real
    peak = float(inten.max()) if inten.size else 0.0
    return inten >= _VISIBLE * peak if peak > 0 else flat


def measured_vectors(
    positions: np.ndarray, center: tuple[int, int], d_meas: np.ndarray,
    s_row: float, s_col: float,
) -> np.ndarray:
    """(n, 2) in-plane reciprocal vectors: direction of each spot from the
    centre in physical units, length 1/d. Image rows point down, so the row
    axis is flipped to keep a right-handed (x right, y up) frame."""
    dx = (positions[:, 1] - center[1]) * s_col
    dy = -(positions[:, 0] - center[0]) * s_row
    norm = np.hypot(dx, dy)
    with np.errstate(divide="ignore", invalid="ignore"):
        vec = np.column_stack([dx / norm, dy / norm]) / d_meas[:, None]
    return np.asarray(vec, dtype=np.float64)


def _basis_pairs(m: np.ndarray, valid: np.ndarray) -> list[tuple[int, int]]:
    """Distinct short, well-separated spot pairs to anchor the lattice on:
    shortest spot first, partnered with the shortest spot 20°–160° away from
    it. (i, j) and (j, i) are the same basis, so only one is kept."""
    idx = [int(i) for i in np.argsort(np.hypot(m[:, 0], m[:, 1])) if valid[i]]
    unit = m / np.hypot(m[:, 0], m[:, 1])[:, None]
    pairs: list[tuple[int, int]] = []
    seen: set[frozenset[int]] = set()
    for i in idx:
        for j in idx:
            if j == i or frozenset((i, j)) in seen:
                continue
            if abs(float(unit[i] @ unit[j])) < np.cos(np.radians(20.0)):
                pairs.append((i, j))
                seen.add(frozenset((i, j)))
                break
        if len(pairs) >= _MAX_BASES:
            break
    return pairs


def _observed_region(points: np.ndarray) -> Delaunay | None:
    """Convex hull of the matched spots and the beam: where the pattern was
    actually looked at. None when the spots are collinear (a systematic
    row), which bounds no area."""
    try:
        return Delaunay(np.vstack([points, [[0.0, 0.0]]]))
    except (QhullError, ValueError):
        return None


def _span_for(ph: Phase, g_max: float) -> tuple[int, int, int]:
    """Index range that holds every reflection up to |g| = g_max (|h| =
    |g·a| <= |g||a|), on a 0.1 Å⁻¹ step so the cache stays small."""
    g_q = ceil(g_max * 10) / 10
    span = [min(_MAX_INDEX, max(1, ceil(g_q * x))) for x in (ph.a, ph.b, ph.c)]
    while np.prod([2 * n + 1 for n in span]) > _MAX_TABLE:
        span = [max(1, n - 1) for n in span]
    return (span[0], span[1], span[2])


def fit_zone(
    ph: Phase, m: np.ndarray, valid: np.ndarray, tolerance: float,
) -> ZoneFit | None:
    """Best consistent assignment of `ph` to the measured vectors `m`, or None
    when no reflection pair reproduces any basis pair's lengths and angle."""
    m_len = np.hypot(m[:, 0], m[:, 1])
    others = np.nonzero(valid)[0]
    if others.size < 2:
        return None
    t = _tables(ph, _span_for(ph, float(m_len[others].max()) * (1 + tolerance)))
    regions: dict[bytes, Delaunay | None] = {}   # hull per matched-spot set
    members: dict[bytes, np.ndarray] = {}         # visible reflections per zone
    best: ZoneFit | None = None
    for i, j in _basis_pairs(m, valid):
        best = _fit_basis(t, m, m_len, others, i, j, tolerance, best,
                          regions, members)
    return best


def _fit_basis(
    t: _Tables, m: np.ndarray, m_len: np.ndarray, others: np.ndarray,
    i: int, j: int, tolerance: float, best: ZoneFit | None,
    regions: dict[bytes, Delaunay | None], members: dict[bytes, np.ndarray],
) -> ZoneFit | None:
    """Try every reflection pair (gi, gj) matching basis spots (i, j) in
    length and angle, all at once; return the best fit so far."""
    cand_i = np.nonzero(np.abs(t.g_len - m_len[i]) / t.g_len < tolerance)[0]
    cand_j = np.nonzero(np.abs(t.g_len - m_len[j]) / t.g_len < tolerance)[0]
    if cand_i.size == 0 or cand_j.size == 0:
        return best
    meas_ang = np.arccos(np.clip(m[i] @ m[j] / (m_len[i] * m_len[j]), -1.0, 1.0))
    gi_all, gj_all = t.g[cand_i], t.g[cand_j]
    cos = (gi_all @ gj_all.T) / np.outer(t.g_len[cand_i], t.g_len[cand_j])
    ang_all = np.abs(np.arccos(np.clip(cos, -1.0, 1.0)) - meas_ang)
    pa, pb = np.nonzero(ang_all < np.radians(ANGLE_TOL_DEG))
    if pa.size == 0:
        return best
    gi, gj = gi_all[pa], gj_all[pb]                       # (P, 3)
    ang_err = ang_all[pa, pb]
    n_valid = int(others.size)

    # every valid spot as α·m_i + β·m_j (exact in 2-D) → predicted g per pair
    coef = np.linalg.solve(np.column_stack([m[i], m[j]]), m[others].T).T  # (n, 2)
    p = coef[None, :, :1] * gi[:, None, :] + coef[None, :, 1:] * gj[:, None, :]
    hk = np.rint(p @ t.direct.T).astype(int)              # (P, n, 3) nearest hkl
    span = np.array(t.span)
    in_span = np.all(np.abs(hk) <= span, axis=2)
    sel = np.where(in_span[..., None], hk + span, 0)
    ok = in_span & t.grid[sel[..., 0], sel[..., 1], sel[..., 2]]
    g_round = hk @ t.recip
    gr_len = np.linalg.norm(g_round, axis=2)
    with np.errstate(divide="ignore", invalid="ignore"):
        err = np.linalg.norm(p - g_round, axis=2) / gr_len
        d_err = np.abs(m_len[others][None, :] - gr_len) / gr_len
    # on the lattice (consistent hkl) AND at the measured spacing
    hit = ok & (err < tolerance) & (d_err < tolerance)
    n = hit.sum(axis=1)

    zones = _zones(t.hkl[cand_i[pa]], t.hkl[cand_j[pb]])
    repeat = np.linalg.norm(zones @ t.direct, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        resid = (np.where(n > 0, (d_err * hit).sum(axis=1) / np.maximum(n, 1), np.inf)
                 + ang_err
                 + _ZONE_PRIOR * np.maximum(0.0, np.log2(repeat / t.a_mean)))
    upper = n / n_valid                     # score if nothing is missing
    # best-first: once a pair cannot beat `best` even with nothing
    # missing, no later one can (missing spots only lower the score)
    for q in np.lexsort((resid, -upper)):
        if n[q] < 2 or (best is not None
                        and (upper[q], -resid[q]) <= (best.score, -best.residual)):
            break
        h = hit[q]
        key = h.tobytes()
        if key not in regions:
            regions[key] = _observed_region(m[others[h]])
        zkey = zones[q].tobytes()
        if zkey not in members:
            members[zkey] = np.nonzero(((t.hkl @ zones[q]) == 0) & t.visible)[0]
        missing = _count_missing(t, members[zkey], hk[q][h], regions[key], gi[q], gj[q],
                                 m[i], m[j], float(gr_len[q][h].max()) * (1 + tolerance))
        score = int(n[q]) / (n_valid + missing)
        if best is None or (score, -resid[q]) > (best.score, -best.residual):
            z = zones[q]
            best = ZoneFit(others[h], hk[q][h], 1.0 / gr_len[q][h],
                           (float(z[0]), float(z[1]), float(z[2])),
                           float(resid[q]), missing, score)
    return best


def _zones(h1: np.ndarray, h2: np.ndarray) -> np.ndarray:
    """Row-wise [uvw] = h1 × h2, reduced by the gcd and sign-normalised
    (first non-zero component positive). A zero row: collinear pair."""
    uvw = np.cross(h1, h2)
    g = np.gcd.reduce(np.abs(uvw), axis=1)
    uvw = uvw // np.where(g == 0, 1, g)[:, None]
    first = uvw[np.arange(len(uvw)), np.argmax(uvw != 0, axis=1)]
    return np.asarray(np.where((first < 0)[:, None], -uvw, uvw), dtype=np.int64)


def _count_missing(
    t: _Tables, in_zone: np.ndarray, seen_hkl: np.ndarray, region: Delaunay | None,
    gi: np.ndarray, gj: np.ndarray, mi: np.ndarray, mj: np.ndarray, g_max: float,
) -> int:
    """Strong in-zone reflections the fit puts INSIDE the observed region
    (hull of the matched spots and the beam) that no matched spot accounts
    for. Reflections outside it — the far side of a one-sided pattern, past
    an ROI edge — say nothing about the fit and are not counted."""
    if region is None:
        return 0
    cand = in_zone[t.g_len[in_zone] <= g_max]          # strong, in-zone, in range
    if cand.size == 0:
        return 0
    # in-zone g = α gi + β gj exactly; map to the detector as α mi + β mj
    basis = np.vstack([gi, gj])                          # (2, 3)
    ab = t.g[cand] @ basis.T @ np.linalg.inv(basis @ basis.T)
    pos = ab @ np.vstack([mi, mj])
    inside = region.find_simplex(pos) >= 0
    seen = np.isin(t.key[cand], _code(seen_hkl, t.span))
    return int((inside & ~seen).sum())


def rerank_by_zone(
    cands: list, db: list[Phase], positions: np.ndarray,
    center: tuple[int, int], d_meas: np.ndarray, valid: np.ndarray,
    weights: tuple[float, float], tolerance: float,
) -> list:
    """Re-score d-only candidates (`IndexCandidate`s, same order as `db`) by
    zone-axis consistency when the spots form a single-crystal pattern.
    `weights` is the physical (row, column) scale of one pixel step.

    Spots implying d < 0.33 Å are no reflection (a wrong calibration, or
    noise) and take no part. The pattern counts as a spot pattern when the
    best phase indexes at
    least half of the valid spots (and at least 3) consistently; otherwise
    — a ring pattern, a systematic row, too few spots — the d-only result
    stands. In spot mode every score means the same thing: the fraction of
    spots a phase indexes CONSISTENTLY (one zone, signed hkl), discounted
    by strong reflections it predicts in the observed region that are not
    there. A phase with no consistent fit cannot explain the pattern as a
    single crystal and scores 0; its d-only matches are kept for reference
    (``method="d-spacing"``)."""
    m = measured_vectors(positions, center, d_meas, weights[0], weights[1])
    with np.errstate(invalid="ignore"):
        valid = valid & (np.hypot(m[:, 0], m[:, 1]) <= _MAX_G)
    n_valid = int(valid.sum())
    if n_valid < 3:
        return cands
    fits = [fit_zone(ph, m, valid, tolerance) for ph in db]
    best_n = max((f.matched_idx.size for f in fits if f is not None), default=0)
    if best_n < max(3, 0.5 * n_valid):
        return cands

    out = []
    for c, f in zip(cands, fits, strict=True):
        if f is None:
            out.append((np.inf, replace(c, score=0.0, method="d-spacing")))
            continue
        idx = f.matched_idx
        out.append((f.residual, replace(
            c, score=f.score, n_matched=int(idx.size),
            matched_hkl=f.matched_hkl, matched_d=d_meas[idx], ref_d=f.ref_d,
            zone_axis=f.zone_axis, matched_idx=idx, method="zone",
        )))
    out.sort(key=lambda t: (-t[1].score, t[0]))
    return [t[1] for t in out]
