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

Pure numpy; no MATLAB counterpart (the reference indexes by d only).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import gcd

import numpy as np

from fermiviewer.calc.crystal import Phase, _allowed
from fermiviewer.calc.scattering_factors import build_basis_model, reflection_intensity

__all__ = ["ZoneFit", "fit_zone", "measured_vectors", "reciprocal_vectors"]

#: angle mismatch allowed between a measured spot pair and a reflection pair
ANGLE_TOL_DEG = 3.0
#: how many basis pairs (shortest non-collinear first) to try per phase, so a
#: spurious spot in the basis does not sink the right phase
_MAX_BASES = 4
#: kinematic |F|² (relative to the strongest reflection) above which an
#: in-zone reflection is expected to show up as a spot
_VISIBLE = 0.01


@dataclass(frozen=True)
class ZoneFit:
    """One phase's best self-consistent spot assignment."""

    matched_idx: np.ndarray       # indices into the input spots
    matched_hkl: np.ndarray       # (n, 3) signed integer hkl per matched spot
    ref_d: np.ndarray             # d of each assigned reflection (Å)
    zone_axis: tuple[float, float, float]
    residual: float               # mean relative d error + basis angle error (rad)
    n_missing: int = 0            # strong in-zone reflections with no spot
    score: float = 0.0            # matched / (valid spots + missing)


@lru_cache(maxsize=256)
def _phase_tables(ph: Phase, max_hkl: int) -> tuple[np.ndarray, ...]:
    """Per-phase lookup tables, cached: indexing re-runs on every ROI drag
    against the whole phase database."""
    hkl, g, direct = reciprocal_vectors(ph, max_hkl)
    g_len = np.linalg.norm(g, axis=1)
    return hkl, g, direct, g_len, _visible(ph, hkl, g_len)


def reciprocal_vectors(ph: Phase, max_hkl: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(hkl, g, direct)``: every lattice-allowed reflection up to `max_hkl`,
    its Cartesian reciprocal vector g (|g| = 1/d, Å⁻¹), and the direct basis
    (rows a, b, c) used to map a g back to fractional hkl (h = g·a)."""
    al, be, ga = np.radians([ph.alpha, ph.beta, ph.gamma])
    a_vec = np.array([ph.a, 0.0, 0.0])
    b_vec = np.array([ph.b * np.cos(ga), ph.b * np.sin(ga), 0.0])
    cx = ph.c * np.cos(be)
    cy = ph.c * (np.cos(al) - np.cos(be) * np.cos(ga)) / np.sin(ga)
    cz = np.sqrt(max(ph.c**2 - cx**2 - cy**2, 0.0))
    direct = np.vstack([a_vec, b_vec, [cx, cy, cz]])
    recip = np.linalg.inv(direct).T          # rows a*, b*, c*
    rng = range(-max_hkl, max_hkl + 1)
    hkl = np.array([
        (h, k, l) for h in rng for k in rng for l in rng  # noqa: E741
        if (h, k, l) != (0, 0, 0) and _allowed(h, k, l, ph.centering.upper())
    ])
    return hkl, hkl @ recip, direct


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
    """Short, well-separated spot pairs to anchor the lattice on: shortest
    spot first, partnered with the shortest spot 20°–160° away from it."""
    idx = [int(i) for i in np.argsort(np.hypot(m[:, 0], m[:, 1])) if valid[i]]
    pairs: list[tuple[int, int]] = []
    for i in idx:
        for j in idx:
            if j == i:
                continue
            cos = float(m[i] @ m[j] / (np.linalg.norm(m[i]) * np.linalg.norm(m[j])))
            if abs(cos) < np.cos(np.radians(20.0)):
                pairs.append((i, j))
                break
        if len(pairs) >= _MAX_BASES:
            break
    return pairs


def _visible(ph: Phase, hkl: np.ndarray, g_len: np.ndarray) -> np.ndarray:
    """Which allowed reflections are kinematically strong enough to see:
    |F|² from the atomic basis when the phase has one (so e.g. Si 200 —
    diamond-glide extinct — is not expected), else all centering-allowed."""
    if not ph.basis:
        return np.ones(len(hkl), dtype=bool)
    try:
        bm = build_basis_model(ph.basis)
        inten = np.array([
            reflection_intensity(bm, (int(r[0]), int(r[1]), int(r[2])), gl / 2.0)
            for r, gl in zip(hkl, g_len, strict=True)
        ])
    except KeyError:      # element without a tabulated scattering factor
        return np.ones(len(hkl), dtype=bool)
    peak = float(inten.max()) if inten.size else 0.0
    return inten >= _VISIBLE * peak if peak > 0 else np.ones(len(hkl), dtype=bool)


def _zone_from(h1: np.ndarray, h2: np.ndarray) -> tuple[float, float, float]:
    """[uvw] = h1 × h2, reduced and sign-normalised (first non-zero > 0)."""
    uvw = np.cross(h1.astype(int), h2.astype(int))
    g = gcd(gcd(int(abs(uvw[0])), int(abs(uvw[1]))), int(abs(uvw[2]))) or 1
    uvw = uvw // g
    nz = uvw[np.nonzero(uvw)[0]]
    if nz.size and nz[0] < 0:
        uvw = -uvw
    return (float(uvw[0]), float(uvw[1]), float(uvw[2]))


def fit_zone(
    ph: Phase, m: np.ndarray, valid: np.ndarray, tolerance: float, max_hkl: int,
) -> ZoneFit | None:
    """Best consistent assignment of `ph` to the measured vectors `m`, or None
    when no reflection pair reproduces any basis pair's lengths and angle."""
    hkl, g, direct, g_len, visible = _phase_tables(ph, max_hkl)
    m_len = np.hypot(m[:, 0], m[:, 1])
    allowed = {tuple(h) for h in hkl.tolist()}   # nonzero, lattice-allowed
    n_valid = int(valid.sum())
    ang_tol = np.radians(ANGLE_TOL_DEG)
    best: ZoneFit | None = None

    for i, j in _basis_pairs(m, valid):
        cand_i = np.nonzero(np.abs(g_len - m_len[i]) / g_len < tolerance)[0]
        cand_j = np.nonzero(np.abs(g_len - m_len[j]) / g_len < tolerance)[0]
        if cand_i.size == 0 or cand_j.size == 0:
            continue
        # every other spot as a·m_i + b·m_j (exact in 2-D)
        basis = np.column_stack([m[i], m[j]])
        others = np.nonzero(valid)[0]
        coef = np.linalg.solve(basis, m[others].T).T      # (n_valid, 2)
        meas_ang = np.arccos(np.clip(
            m[i] @ m[j] / (m_len[i] * m_len[j]), -1.0, 1.0))
        gi, gj = g[cand_i], g[cand_j]
        cos = (gi @ gj.T) / np.outer(g_len[cand_i], g_len[cand_j])
        ang_err = np.abs(np.arccos(np.clip(cos, -1.0, 1.0)) - meas_ang)
        for a, b in zip(*np.nonzero(ang_err < ang_tol), strict=True):
            p = coef[:, :1] * gi[a] + coef[:, 1:] * gj[b]   # predicted g
            frac = p @ direct.T                              # fractional hkl
            hk = np.rint(frac).astype(int)
            ok = np.array([tuple(h) in allowed for h in hk.tolist()])
            g_round = hk @ np.linalg.inv(direct).T
            gr_len = np.linalg.norm(g_round, axis=1)
            with np.errstate(divide="ignore", invalid="ignore"):
                err = np.linalg.norm(p - g_round, axis=1) / gr_len
                d_err = np.abs(m_len[others] - gr_len) / gr_len
            # on the lattice (consistent hkl) AND at the measured spacing
            hit = ok & (err < tolerance) & (d_err < tolerance)
            n = int(hit.sum())
            if n < 2:
                continue
            resid = float(d_err[hit].mean() + ang_err[a, b])
            zone = _zone_from(hkl[cand_i[a]], hkl[cand_j[b]])
            # a lattice that also predicts strong spots that are NOT there
            # (a dense high-index zone of a big cell) is a worse explanation
            in_zone = ((hkl @ np.asarray(zone, dtype=int)) == 0) & visible & (
                g_len <= gr_len[hit].max() * (1 + tolerance))
            seen = {tuple(h) for h in hk[hit]}
            missing = sum(tuple(h) not in seen for h in hkl[in_zone])
            score = n / (n_valid + missing)
            if best is None or (score, -resid) > (best.score, -best.residual):
                best = ZoneFit(others[hit], hk[hit], 1.0 / gr_len[hit],
                               zone, resid, missing, score)
    return best


def rerank_by_zone(
    cands: list, db: list[Phase], positions: np.ndarray,
    center: tuple[int, int], d_meas: np.ndarray, valid: np.ndarray,
    weights: tuple[float, float], tolerance: float, max_hkl: int,
) -> list:
    """Re-score d-only candidates (`IndexCandidate`s, same order as `db`) by
    zone-axis consistency when the spots form a single-crystal pattern.
    `weights` is the physical (row, column) scale of one pixel step.

    The pattern counts as a spot pattern when the best phase indexes at
    least half of the valid spots (and at least 3) consistently; otherwise
    — a ring pattern, a systematic row, too few spots — the d-only result
    stands. In spot mode a phase's score is the fraction of spots it
    indexes CONSISTENTLY (same zone, signed hkl), discounted by strong
    in-zone reflections the fit predicts but that are not there; ties go
    to the smaller length/angle residual. Phases with no consistent fit
    keep their d-only result (``method="d-spacing"``) and rank after every
    phase that has one."""
    from dataclasses import replace

    m = measured_vectors(positions, center, d_meas, weights[0], weights[1])
    fits = [fit_zone(ph, m, valid, tolerance, max_hkl) for ph in db]
    n_valid = int(valid.sum())
    best_n = max((f.matched_idx.size for f in fits if f is not None), default=0)
    if best_n < max(3, 0.5 * n_valid):
        return cands

    out = []
    for c, f in zip(cands, fits, strict=True):
        if f is None:     # keep its d-only result, ranked after every zone fit
            out.append((1, np.inf, c))
            continue
        idx = f.matched_idx
        out.append((0, f.residual, replace(
            c, score=f.score, n_matched=int(idx.size),
            matched_hkl=f.matched_hkl, matched_d=d_meas[idx], ref_d=f.ref_d,
            zone_axis=f.zone_axis, matched_idx=idx, method="zone",
        )))
    out.sort(key=lambda t: (t[0], -t[2].score, t[1]))
    return [t[2] for t in out]
