"""Atom-column lattice geometry + peak-pair strain (split from atoms.py).

Lattice basis vectors from nearest-neighbour direction histograms, and
per-column strain from displacement-gradient plane fits against that ideal
lattice. Kept out of ``atoms.py`` (was 498 lines) to respect the 500-line
god-module ceiling — detection, sub-pixel Gaussian fitting, and sublattice
clustering stayed there; re-exported from atoms.py so existing imports are
unaffected.

Positions are (x, y) = (col, row), 1-based, throughout — same convention as
atoms.py.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = [
    "LatticeVectors",
    "PairStrain",
    "find_lattice_vectors",
    "peak_pair_strain",
]


# ── lattice basis ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class LatticeVectors:
    a1: np.ndarray
    a2: np.ndarray
    origin: np.ndarray
    spacing: float
    valid: bool


def _ang_diff(a: np.ndarray, b: float) -> np.ndarray:
    """Smallest signed angle difference mod π (directions fold 180°)."""
    out: np.ndarray = np.mod(a - b + np.pi / 2, np.pi) - np.pi / 2
    return out


def find_lattice_vectors(
    positions: np.ndarray,
    neighbors: int = 6,
    min_angle_deg: float = 15.0,
    max_sample: int = 400,
) -> LatticeVectors:
    """Lattice basis from nearest-neighbour direction histograms."""
    pos = np.asarray(positions, dtype=np.float64)
    n = pos.shape[0]
    invalid = LatticeVectors(
        np.full(2, np.nan), np.full(2, np.nan), np.full(2, np.nan),
        np.nan, False,
    )
    if n < 4:
        return invalid

    ctr = pos.mean(axis=0)
    origin = pos[int(np.argmin(((pos - ctr) ** 2).sum(axis=1)))]

    m = min(n, max_sample)
    q = pos[:m]
    d2 = np.maximum(
        (q**2).sum(1)[:, None] - 2 * q @ pos.T + (pos**2).sum(1)[None, :],
        0,
    )
    vecs = []
    nn_dist = np.zeros(m)
    for i in range(m):
        order = np.argsort(d2[i], kind="stable")[1:]  # drop self
        kk = min(neighbors, order.size)
        if kk < 1:
            continue
        nn_dist[i] = np.sqrt(d2[i, order[0]])
        vecs.extend(pos[order[:kk]] - q[i])
    v = np.asarray(vecs)
    if v.shape[0] < 3:
        return invalid

    spacing = float(np.median(nn_dist[nn_dist > 0]))
    length = np.hypot(v[:, 0], v[:, 1])
    v = v[(length > 0.3 * spacing) & (length < 1.8 * spacing)]
    if v.shape[0] < 3:
        return invalid
    flip = (v[:, 0] < 0) | ((np.abs(v[:, 0]) < 1e-9) & (v[:, 1] < 0))
    v[flip] = -v[flip]
    ang = np.arctan2(v[:, 1], v[:, 0])

    edges = np.linspace(-np.pi / 2, np.pi / 2, 37)
    hist, _ = np.histogram(ang, bins=edges)
    b1 = int(np.argmax(hist))
    c1 = (edges[b1] + edges[b1 + 1]) / 2
    tol = np.deg2rad(12)
    sel1 = np.abs(_ang_diff(ang, c1)) <= tol
    if sel1.sum() < 2:
        return invalid
    a1 = v[sel1].mean(axis=0)

    far = np.abs(_ang_diff(ang, c1)) > np.deg2rad(min_angle_deg)
    if far.sum() < 2:
        return invalid
    hist2, _ = np.histogram(ang[far], bins=edges)
    b2 = int(np.argmax(hist2))
    c2 = (edges[b2] + edges[b2 + 1]) / 2
    sel2 = far & (np.abs(_ang_diff(ang, c2)) <= tol)
    if sel2.sum() < 2:
        return invalid
    a2 = v[sel2].mean(axis=0)

    if abs(a1[0] * a2[1] - a1[1] * a2[0]) < 1e-6 * spacing**2:
        return invalid
    return LatticeVectors(a1=a1, a2=a2, origin=origin, spacing=spacing,
                          valid=True)


# ── peak-pair strain ──────────────────────────────────────────────────


@dataclass(frozen=True)
class PairStrain:
    exx: np.ndarray
    eyy: np.ndarray
    exy: np.ndarray
    rotation: np.ndarray
    displacement: np.ndarray
    indices: np.ndarray
    ref_vectors: np.ndarray
    origin: np.ndarray
    valid: bool


def peak_pair_strain(
    positions: np.ndarray,
    ref_vectors: np.ndarray | None = None,
    origin: np.ndarray | None = None,
    neighbors: int = 8,
) -> PairStrain:
    """Per-column strain from displacement gradients vs the ideal lattice."""
    pos = np.asarray(positions, dtype=np.float64)
    n = pos.shape[0]
    nanv = np.full(n, np.nan)
    invalid = PairStrain(
        nanv, nanv.copy(), nanv.copy(), nanv.copy(),
        np.full((n, 2), np.nan), np.full((n, 2), np.nan),
        np.full((2, 2), np.nan), np.full(2, np.nan), False,
    )
    if n < 4:
        return invalid

    if ref_vectors is not None and origin is not None:
        ref_v = np.asarray(ref_vectors, dtype=np.float64)
        org = np.asarray(origin, dtype=np.float64).ravel()
    else:
        lv = find_lattice_vectors(pos)
        if not lv.valid:
            return invalid
        ref_v = np.array([lv.a1, lv.a2])
        org = lv.origin
    b = ref_v.T  # columns a1, a2
    if abs(np.linalg.det(b)) < 1e-9:
        return invalid

    frac = np.linalg.solve(b, (pos - org).T)
    idx = np.round(frac)
    ideal = org + (b @ idx).T
    u = pos - ideal

    d2 = np.maximum(
        (ideal**2).sum(1)[:, None]
        - 2 * ideal @ ideal.T
        + (ideal**2).sum(1)[None, :],
        0,
    )
    exx = nanv.copy()
    eyy = nanv.copy()
    exy = nanv.copy()
    rot = nanv.copy()
    for i in range(n):
        order = np.argsort(d2[i], kind="stable")
        kk = min(neighbors + 1, order.size)  # include self
        nb = order[:kk]
        if kk < 4:
            continue
        dx = ideal[nb, 0] - ideal[i, 0]
        dy = ideal[nb, 1] - ideal[i, 1]
        a = np.column_stack([np.ones(kk), dx, dy])
        gx, *_ = np.linalg.lstsq(a, u[nb, 0], rcond=None)
        gy, *_ = np.linalg.lstsq(a, u[nb, 1], rcond=None)
        exx[i] = gx[1]
        eyy[i] = gy[2]
        exy[i] = 0.5 * (gx[2] + gy[1])
        rot[i] = 0.5 * (gy[1] - gx[2])

    return PairStrain(
        exx=exx, eyy=eyy, exy=exy, rotation=rot,
        displacement=u, indices=idx.T,
        ref_vectors=ref_v, origin=org, valid=True,
    )
