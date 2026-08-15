"""Elliptic Fourier shape descriptors (SHAPE_ANALYSIS_PLAN Tier-2 item #4).

Kuhl, F.P. & Giardina, C.R. (1982). "Elliptic Fourier features of a
closed contour." Computer Graphics and Image Processing, 18(3), 236-258.
https://doi.org/10.1016/0146-664X(82)90112-1

`calc/contours.py`'s `trace_outer_contour`/`trace_region_with_holes`
produce the closed polygon rings this module consumes: `Contour.points`,
an (N, 2) array of (row, col) vertices with the ring closed IMPLICITLY
(no repeated first vertex) -- exactly the convention `efd_coefficients`
expects below.

Normalization variant implemented (Kuhl & Giardina Section IV -- the
three-step procedure that every EFD library which claims "the K&G
normalization" implements; this is a from-scratch reimplementation from
the paper's formulas, not a port of any of them -- pyefd/momocs/SHAPE
were NOT consulted, nor was py4DSTEM/pyxem, which are AGPL and out of
scope for this Apache-2.0 project regardless):

1. STARTING-POINT normalization: rotate the parametrization itself (a
   phase shift, `theta_1`) so that harmonic 1's own ellipse starts its
   trace at the end of its semi-major axis. Applied to harmonic n as an
   `n * theta_1` rotation, since the n-th harmonic completes n cycles per
   trip around the fundamental.
2. ROTATION normalization: rotate the shape itself (a spatial rotation,
   `psi_1`, applied identically to every harmonic) so harmonic 1's
   semi-major axis lies along +x (+col).
3. SCALE normalization: divide every coefficient by `|a_1|` (harmonic 1's
   now-canonical x-half-axis length) so the new `a_1 = +-1`.

Step 1's `arctan2` has a two-fold ambiguity: `theta_1` and `theta_1 + pi`
zero the same discriminant, because the starting vertex could sit at
EITHER end of harmonic 1's major axis. This does NOT need an explicit
correction, because step 2 absorbs it automatically: `psi_1` is defined
as the polar angle of the harmonic-1 vector `(a_1', c_1')` that step 1
just produced, and rotating any nonzero vector by the NEGATIVE of its
OWN polar angle always lands it on the nonnegative a-axis, at distance
`hypot(a_1', c_1')` -- a tautology of polar coordinates, true for
EITHER `theta_1` branch, since the two branches produce `(a_1', c_1')`
and its exact negation, and `psi_1`'s definition tracks whichever one
step 1 actually returned. So `out[0, 0] >= 0` always holds after step 2,
by construction, not by a follow-up sign-flip -- an earlier version of
this module carried an explicit "if a_1 < 0, flip odd harmonics" branch
for this, which mutation testing showed was unreachable dead code
(`tests/test_efd.py`'s starting-point-invariance test, including a start
on the opposite end of the major axis, passed identically with that
branch deleted). Two tracings of the SAME shape that start on opposite
ends of the major axis still converge to the same descriptor -- that
invariance is real and pinned by `tests/test_efd.py` -- it is just
provided by step 2's construction, not by extra code.

Reflections (mirrored winding) are deliberately NOT normalized away:
`calc/contours.py` already canonicalizes winding direction
(`_canonicalize`, signed area >= 0) before a ring reaches this module, so
every input this module sees is already consistently wound, and handling
a second, un-canonicalized winding convention here would be dead code.

`DEFAULT_N_HARMONICS = 10` matches Kuhl & Giardina's own worked examples
and the general EFD rule of thumb that ~10 harmonics captures a
particle-scale outline's shape without fitting digitization noise. It is
a plain module constant, never a hidden literal -- every function below
takes `n_harmonics` as an explicit, caller-overridable parameter that
defaults to it.

A ring needs at least `n_harmonics` vertices to be accepted at that
harmonic count. Note this is a DEFENSIVE floor, not a Nyquist-style
mathematical requirement -- the coefficient integral below is a
closed-form quadrature over each polygon EDGE, exact for any harmonic
order down to a 3-vertex triangle, unlike sampling a continuous signal.
The floor exists because a ring with far fewer vertices than the
requested harmonic count is usually a sign something upstream went
wrong (an over-simplified trace, or a caller asking for more shape
detail than the ring could ever carry) rather than a computation that
should silently proceed. Fewer than `n_harmonics` vertices raises
`ValueError`; `routes/shape_id.py` turns that into a 422 naming the
offending region.

PURE: numpy only. No fastapi/pydantic/routes imports -- enforced by
tests/test_repo_integrity.py for every module under calc/.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = [
    "DEFAULT_N_HARMONICS",
    "EfdDescriptor",
    "efd_coefficients",
    "efd_descriptor",
    "efd_distance",
    "normalize_coefficients",
]

DEFAULT_N_HARMONICS = 10


@dataclass(frozen=True)
class EfdDescriptor:
    """A normalized elliptic Fourier descriptor.

    `coeffs` is `(n_harmonics, 4)`: row `n - 1` holds `[a_n, b_n, c_n,
    d_n]` (1-indexed harmonics), normalized for scale, rotation and
    starting point per the module docstring. Two descriptors are only
    comparable (`efd_distance`) when computed with the SAME
    `n_harmonics` -- the field is carried alongside the array so callers
    can check before comparing rather than silently truncating.
    """

    coeffs: np.ndarray
    n_harmonics: int


def _min_points(n_harmonics: int) -> int:
    return max(3, n_harmonics)


def efd_coefficients(
    points_rc: np.ndarray, n_harmonics: int = DEFAULT_N_HARMONICS
) -> np.ndarray:
    """RAW (un-normalized) elliptic Fourier coefficients of a closed ring.

    `points_rc` is an `(N, 2)` array of `(row, col)` vertices using the
    `calc/contours.py` convention: the ring is closed IMPLICITLY (the
    last point does NOT repeat the first). Returns `(n_harmonics, 4)`:
    row `n - 1` is `[a_n, b_n, c_n, d_n]` per Kuhl & Giardina eqs. 1-4,
    with their `x <- col` and `y <- row`.

    Raises `ValueError` if `points_rc` is malformed or has fewer than
    `max(3, n_harmonics)` DISTINCT vertices (see module docstring).
    """
    pts = np.asarray(points_rc, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 2:
        raise ValueError("points_rc must be an (N, 2) array of (row, col) points")
    if n_harmonics < 1:
        raise ValueError("n_harmonics must be >= 1")

    min_pts = _min_points(n_harmonics)
    if pts.shape[0] < min_pts:
        raise ValueError(
            f"need >= {min_pts} contour points for {n_harmonics} harmonics, "
            f"got {pts.shape[0]}"
        )

    closed = np.vstack([pts, pts[:1]])
    delta = np.diff(closed, axis=0)  # (N, 2): (drow, dcol) per segment
    seg_len = np.hypot(delta[:, 0], delta[:, 1])
    distinct = seg_len > 1e-12  # drop coincident consecutive vertices
    delta, seg_len = delta[distinct], seg_len[distinct]
    if delta.shape[0] < min_pts:
        raise ValueError(
            f"need >= {min_pts} DISTINCT contour points for {n_harmonics} "
            f"harmonics, got {delta.shape[0]}"
        )

    t = np.concatenate([[0.0], np.cumsum(seg_len)])
    perimeter = t[-1]
    if perimeter <= 0:
        raise ValueError("degenerate contour: zero perimeter")

    orders = np.arange(1, n_harmonics + 1, dtype=np.float64)
    phi = 2.0 * np.pi * np.outer(orders, t) / perimeter  # (n_harmonics, N+1)
    d_cos = np.cos(phi[:, 1:]) - np.cos(phi[:, :-1])
    d_sin = np.sin(phi[:, 1:]) - np.sin(phi[:, :-1])
    const = perimeter / (2.0 * np.pi**2 * orders**2)

    dx = delta[:, 1] / seg_len  # col -> x
    dy = delta[:, 0] / seg_len  # row -> y
    a_n = const * np.sum(dx * d_cos, axis=1)
    b_n = const * np.sum(dx * d_sin, axis=1)
    c_n = const * np.sum(dy * d_cos, axis=1)
    d_n = const * np.sum(dy * d_sin, axis=1)
    return np.stack([a_n, b_n, c_n, d_n], axis=1)


def normalize_coefficients(coeffs: np.ndarray) -> np.ndarray:
    """Scale/rotation/starting-point normalization -- module docstring
    steps 1-3. Step 2 also resolves step 1's theta_1 two-fold ambiguity
    as a side effect of its own definition (module docstring) -- no
    separate correction step is needed."""
    out = np.array(coeffs, dtype=np.float64, copy=True)
    if out.ndim != 2 or out.shape[1] != 4 or out.shape[0] < 1:
        raise ValueError("coeffs must be an (n_harmonics, 4) array")
    n_harm = out.shape[0]

    a1, b1, c1, d1 = out[0]
    if a1 == 0.0 and b1 == 0.0 and c1 == 0.0 and d1 == 0.0:
        raise ValueError("degenerate first harmonic (zero-area contour?)")

    # Step 1 -- starting-point (phase) normalization.
    theta1 = 0.5 * np.arctan2(
        2.0 * (a1 * b1 + c1 * d1), a1**2 - b1**2 + c1**2 - d1**2
    )
    n = np.arange(1, n_harm + 1, dtype=np.float64)
    cos_t, sin_t = np.cos(n * theta1), np.sin(n * theta1)
    a, b, c, d = out[:, 0], out[:, 1], out[:, 2], out[:, 3]
    out = np.stack(
        [
            a * cos_t + b * sin_t,
            -a * sin_t + b * cos_t,
            c * cos_t + d * sin_t,
            -c * sin_t + d * cos_t,
        ],
        axis=1,
    )

    # Step 2 -- rotation normalization.
    a1, b1, c1, d1 = out[0]
    psi1 = np.arctan2(c1, a1)
    cp, sp = np.cos(psi1), np.sin(psi1)
    a, b, c, d = out[:, 0], out[:, 1], out[:, 2], out[:, 3]
    out = np.stack(
        [
            cp * a + sp * c,
            cp * b + sp * d,
            -sp * a + cp * c,
            -sp * b + cp * d,
        ],
        axis=1,
    )

    # Step 3 -- scale normalization. `out[0, 0]` is ALREADY >= 0 here (see
    # module docstring: step 2 rotates (a1, c1) onto the nonnegative
    # a-axis by construction, for either branch of step 1's theta_1), so
    # dividing by it directly -- not abs(it) -- is what actually
    # normalizes scale; `abs` is kept only as numerical-noise insurance.
    scale = abs(out[0, 0])
    if scale < 1e-12:
        raise ValueError("degenerate normalized descriptor (zero scale)")
    out /= scale
    return out


def efd_descriptor(
    points_rc: np.ndarray, n_harmonics: int = DEFAULT_N_HARMONICS
) -> EfdDescriptor:
    """Normalized EFD of a closed ring -- `efd_coefficients` followed by
    `normalize_coefficients`, bundled with the `n_harmonics` used."""
    raw = efd_coefficients(points_rc, n_harmonics=n_harmonics)
    return EfdDescriptor(coeffs=normalize_coefficients(raw), n_harmonics=n_harmonics)


def efd_distance(d1: EfdDescriptor, d2: EfdDescriptor) -> float:
    """L2 distance between two normalized descriptors' flattened
    coefficient arrays. `0` for (near-)identical shapes; grows with
    shape dissimilarity. Requires matching `n_harmonics` -- comparing
    descriptors computed at different harmonic counts is a caller bug,
    not a silent truncation."""
    if d1.n_harmonics != d2.n_harmonics:
        raise ValueError(
            "descriptors must share the same n_harmonics to compare "
            f"(got {d1.n_harmonics} and {d2.n_harmonics})"
        )
    return float(np.linalg.norm((d1.coeffs - d2.coeffs).ravel()))
