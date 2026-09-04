"""Cauchy--Crofton perimeter on a possibly RECTANGULAR pixel lattice.

`skimage.measure.perimeter_crofton` refuses non-square pixels outright
(``NotImplementedError: 'perimeter' supports isotropic spacings only``),
and `regionprops(spacing=...)` inherits that refusal. Everything else
regionprops reports -- area, equivalent diameter, Feret, the moment-ellipse
axes, eccentricity, orientation -- honours anisotropic spacing correctly,
so the perimeter was the single quantity standing between this codebase
and physically-correct lengths on anisotropically-sampled data. This
module supplies it.

The estimator
-------------
Crofton's formula writes the boundary length of a planar set as an
integral over all lines meeting it::

    P = 1/2 * integral_0^pi [ integral_R n(theta, t) dt ] dtheta

with ``n(theta, t)`` the number of times the boundary crosses the line of
direction ``theta`` at perpendicular offset ``t``. On a lattice the inner
integral becomes a sum over the discrete family of lattice lines running
in direction ``theta``, weighted by that family's perpendicular spacing::

    P ~= 1/2 * sum_k  dtheta_k * d_k * N_k

For a primitive pixel offset ``(p, q)`` on a lattice with row spacing
``s_r`` and column spacing ``s_c``:

* the physical direction is ``(p*s_r, q*s_c)``;
* ``N_k`` is the number of adjacent-pair transitions at that offset, which
  is exactly the number of boundary crossings along that line family;
* ``d_k = s_r*s_c / |(p*s_r, q*s_c)|`` -- one lattice point per cell of
  area ``s_r*s_c``, and points sit ``|v|`` apart along each line, so the
  lines are that far apart perpendicular to themselves;
* ``dtheta_k`` is the angular sector the direction represents, by the
  midpoint rule on the half-circle (directions are unoriented, period pi).

Why the directions are CHOSEN rather than fixed
-----------------------------------------------
The obvious four offsets -- (0,1), (1,1), (1,0), (1,-1) -- are equally
spaced in angle only when the pixels are square. At 6:1 anisotropy their
physical angles are 0, 80.5, 90 and 99.5 degrees: three of the four crowd
into a 19-degree band and leave a 161-degree gap, which makes the angular
quadrature above very poor. Measured on a rectangle whose true perimeter
is known, that fixed set degrades from -5.5% error at 1:1 to -15.7% at
6:1, while the isotropic estimator's error stays flat at -5.5% for the
same shapes -- so the extra error is the direction set collapsing, not
anything inherent to anisotropic sampling.

`_direction_offsets` therefore picks, for each target angle, the
primitive offset whose PHYSICAL angle is closest. That keeps the bias
near-flat with anisotropy (-5.5% at 1:1, -6.6% at 4:1, -9.4% at 12:1 on
the same rectangle) and, on square pixels, provably selects exactly the
four offsets skimage uses -- so this module reproduces
`skimage.measure.perimeter_crofton(..., directions=4)` bit for bit on
isotropic data. That parity is the backward-compatibility guarantee, and
it is asserted in the tests rather than assumed: existing circularity
values and the `ClassThresholds` cutoffs calibrated against them do not
move.

What it does NOT fix
--------------------
The Crofton family underestimates axis-aligned straight edges; a square
comes out near 0.874 on the circularity scale rather than the textbook
pi/4. That bias is inherited deliberately -- it is what the existing
thresholds are calibrated against -- and is why `directions` is exposed
rather than raised silently.

Coarse sampling is a real limit and no estimator escapes it: a physically
square object rendered onto 3x18 pixels carries only 3 samples across one
axis, and comes out about 14% low however the directions are chosen. The
error shrinks as the region grows (-6% by 30x180). Anisotropic pixels
make small regions coarse in one direction, so small-region perimeters on
strongly anisotropic data deserve the same scepticism as any other
few-pixel measurement.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import ndimage as ndi

# `usable_spacing` lives in `calc/calibration.py` -- it is a general
# calibration predicate, not a perimeter one, and three modules outside
# this one now use it. Re-exported here so existing importers keep
# working unchanged.
from fermiviewer.calc.calibration import physical_angle_rad, usable_spacing

__all__ = ["crofton_perimeter", "crofton_perimeters_by_label", "usable_spacing"]

#: Never search offsets past this. Reaching a 45-degree physical direction
#: needs a component about equal to the pixel aspect ratio, so this caps
#: the aspect ratio that can be fully corrected at 64:1 -- far beyond any
#: real detector, and past it the estimator degrades gracefully toward the
#: fixed-offset behaviour rather than failing.
_MAX_OFFSET = 64


def _physical_angle(p: int, q: int, s_r: float, s_c: float) -> float:
    """Unoriented direction of pixel offset ``(p, q)`` in PHYSICAL space.

    The row step carries `s_r` and the column step `s_c`; getting that
    pairing backwards silently re-weights the angular quadrature. Defined
    once and used by both the offset search and the quadrature so the two
    cannot drift apart.
    """
    # `physical_angle_rad` takes (d_col, d_row); a row offset `p` is the
    # row component and a column offset `q` the column one. Unoriented
    # here (period pi) because a line family has no direction.
    return physical_angle_rad(q, p, (s_r, s_c)) % math.pi


def _direction_offsets(
    spacing: tuple[float, float], directions: int, kmax: int
) -> tuple[tuple[int, int], ...]:
    """Primitive pixel offsets whose PHYSICAL angles best cover [0, pi).

    Returns one offset per target angle ``i*pi/directions``, deduplicated.
    On square pixels with ``directions=4`` this is exactly
    ``((0,1), (1,1), (1,0), (1,-1))`` -- skimage's own set.
    """
    s_r, s_c = spacing
    by_angle: dict[float, tuple[int, int]] = {}
    for p in range(kmax + 1):
        for q in range(-kmax, kmax + 1):
            # (0,0) and the negatives of offsets already seen: a direction
            # is unoriented, so (p,q) and (-p,-q) are the same line family.
            if (p == 0 and q <= 0) or math.gcd(abs(p), abs(q)) != 1:
                continue
            by_angle[_physical_angle(p, q, s_r, s_c)] = (p, q)
    angles = np.array(sorted(by_angle))
    picked: list[tuple[int, int]] = []
    for i in range(directions):
        target = i * math.pi / directions
        gap = np.abs(angles - target)
        gap = np.minimum(gap, math.pi - gap)  # wrap: 179 deg is near 0 deg
        picked.append(by_angle[float(angles[int(np.argmin(gap))])])
    return tuple(dict.fromkeys(picked))


def _transitions(mask: np.ndarray, p: int, q: int) -> int:
    """Boundary crossings along the line family with pixel offset (p, q).

    Counted as adjacent-pair disagreements. `mask` must already be padded
    by at least ``max(|p|, |q|)`` so every crossing at the object's edge
    has a background partner to disagree with.
    """
    h, w = mask.shape
    a = mask[max(p, 0) : h + min(p, 0), max(q, 0) : w + min(q, 0)]
    b = mask[max(-p, 0) : h + min(-p, 0), max(-q, 0) : w + min(-q, 0)]
    return int(np.count_nonzero(a != b))


def crofton_perimeter(
    mask: np.ndarray,
    spacing: tuple[float, float] = (1.0, 1.0),
    directions: int = 4,
) -> float:
    """Crofton perimeter of the truthy region of `mask`, in physical units.

    `spacing` is ``(row_scale, col_scale)`` -- the physical extent of one
    pixel along each axis, in the same unit. Equal scales reproduce
    `skimage.measure.perimeter_crofton(mask, directions)` exactly.

    Returns the total perimeter of everything truthy in `mask`; pass one
    region at a time (or use `crofton_perimeters_by_label`) for per-region
    numbers, since two regions that touch would otherwise share an edge
    that is a real boundary for both.
    """
    if mask.ndim != 2:
        raise ValueError("crofton_perimeter supports 2D masks only")
    if directions < 2:
        raise ValueError("directions must be at least 2")
    s_r, s_c = float(spacing[0]), float(spacing[1])
    if not (math.isfinite(s_r) and math.isfinite(s_c)) or s_r <= 0 or s_c <= 0:
        raise ValueError("spacing entries must be finite and positive")

    binary = (np.asarray(mask) > 0).astype(np.uint8)
    if not binary.any():
        return 0.0

    aspect = max(s_r, s_c) / min(s_r, s_c)
    # A 45-degree physical direction needs a component of about `aspect`;
    # never search past the region itself, where a longer offset would
    # step clean over it and measure the background instead.
    kmax = int(min(max(1, math.ceil(aspect)), max(binary.shape), _MAX_OFFSET))
    offsets = _direction_offsets((s_r, s_c), directions, kmax)

    pad = max(max(abs(p), abs(q)) for p, q in offsets)
    padded = np.pad(binary, pad)

    angle = np.empty(len(offsets))
    spread = np.empty(len(offsets))
    counts = np.empty(len(offsets))
    for i, (p, q) in enumerate(offsets):
        angle[i] = _physical_angle(p, q, s_r, s_c)
        spread[i] = s_r * s_c / math.hypot(p * s_r, q * s_c)
        counts[i] = _transitions(padded, p, q)

    order = np.argsort(angle)
    angle, spread, counts = angle[order], spread[order], counts[order]
    # Midpoint rule on the half-circle: each direction owns half the gap to
    # each neighbour, wrapping through pi because directions are unoriented.
    nxt = np.roll(angle, -1).copy()
    nxt[-1] += math.pi
    prv = np.roll(angle, 1).copy()
    prv[0] -= math.pi
    return 0.5 * float(np.sum(((nxt - prv) / 2.0) * spread * counts))


def crofton_perimeters_by_label(
    labels: np.ndarray,
    spacing: tuple[float, float] = (1.0, 1.0),
    directions: int = 4,
) -> np.ndarray:
    """Per-region Crofton perimeters for a compact 1..n label image.

    Ordered by ascending label, matching `regionprops_table`'s row order
    so the result drops straight into a `ShapeDescriptors`/`GrainStats`
    column. Each region is measured on its OWN mask within its bounding
    box -- the same isolation `regionprops` uses, so two grains that share
    a boundary each count it, as both of their perimeters really include
    it.
    """
    lab = np.asarray(labels)
    n = int(lab.max()) if lab.size else 0
    if n == 0:
        return np.array([], dtype=np.float64)
    out = np.zeros(n, dtype=np.float64)
    for i, sl in enumerate(ndi.find_objects(lab)):
        if sl is None:  # a label absent from a non-compact image
            continue
        out[i] = crofton_perimeter(lab[sl] == i + 1, spacing, directions)
    return out
