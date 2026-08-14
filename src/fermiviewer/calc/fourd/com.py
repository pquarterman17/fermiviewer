"""Center-of-mass map center-resolution policy (PLAN_4DSTEM #7).

``virtual.com_shift_maps`` already implements the per-probe intensity
centroid — the Müller-Caspary center-of-mass definition (Müller-Caspary et
al., "Measurement of atomic electric fields and charge densities from
average momentum transfers using scanning transmission electron
microscopy", Ultramicroscopy 178 (2017)) — and is covered by its own pure
unit tests (PLAN_4DSTEM #6). This module does NOT re-derive that math: its
only job is resolving the descan reference center a caller's COM shift is
measured relative to, then delegating.

A caller-supplied ``center`` wins outright; otherwise the center is
auto-seeded from ``geometry.pattern_center(mean_pattern)`` — the same
auto-center policy ``routes/fourd.py``'s virtual-detector route already
uses for its aperture center (PLAN_4DSTEM #5). py4DSTEM/pyxem (AGPL) were
not consulted for this module or for ``com_shift_maps``.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from fermiviewer.calc.fourd.geometry import pattern_center
from fermiviewer.calc.fourd.virtual import com_shift_maps

__all__ = ["com_maps", "resolve_center"]


def resolve_center(
    center: tuple[float, float] | None = None,
    mean_pattern: np.ndarray | None = None,
) -> tuple[float, float]:
    """The descan reference center, resolved: caller-supplied wins, else
    auto-seeded from ``geometry.pattern_center(mean_pattern)``.

    Exposed separately from ``com_maps`` so a caller can RECORD the center
    it actually used. The auto path resolves to a real number that the
    returned shifts are measured relative to, and a caller that only sees
    its own ``None`` cannot reconstruct it — `routes/fourd.py`'s
    virtual-detector route already resolves-then-records for the same
    reason, and #8's COM→mrad→field calibration needs the value.
    """
    if center is not None:
        return center
    if mean_pattern is None:
        raise ValueError(
            "center is None: pass mean_pattern to auto-seed one via "
            "geometry.pattern_center, or pass an explicit center"
        )
    return pattern_center(mean_pattern)


def com_maps(
    blocks: Iterable[tuple[int, np.ndarray]],
    center: tuple[float, float] | None = None,
    mean_pattern: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Per-probe center-of-mass shift maps, resolving the descan center first.

    ``blocks`` is the same ``(row_start, block)`` streaming protocol
    ``virtual.com_shift_maps``/``virtual_detector`` consume — see their
    docstrings for the exact shape contract.

    ``center`` is the ``(ky, kx)`` descan reference the per-pattern
    centroid is measured relative to.

      * Given explicitly: used exactly as passed, and ``mean_pattern`` is
        never touched (a caller that already knows its center need not
        pay for computing a mean pattern at all — mirrors
        `routes/fourd.py`'s virtual-detector route, which likewise only
        touches ``ds4.mean_pattern`` in the null-center path).
      * ``None`` (auto): resolved via ``geometry.pattern_center(mean_pattern)``,
        which itself falls back to the detector's geometric center for a
        degenerate/all-zero mean pattern (see that function's docstring).
        ``mean_pattern`` is required in this case; a caller that has
        neither a center nor a mean pattern to seed one from gets a clear
        ``ValueError`` rather than a confusing failure deep inside
        ``pattern_center``.

    Delegates the streamed first-moment computation to
    ``virtual.com_shift_maps`` unchanged, including its documented
    degenerate case: a pattern with zero (or non-positive) total
    intensity contributes a shift of 0 at that probe position, regardless
    of ``center``.

    Returns ``(com_y_shift, com_x_shift)``, each ``(scan_y, scan_x)``.
    """
    return com_shift_maps(blocks, resolve_center(center, mean_pattern))
