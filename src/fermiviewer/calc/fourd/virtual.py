"""Streamed virtual-detector reduction over a 4D-STEM scan (pure math).

A 4D-STEM dataset is ``[scan_y, scan_x, det_ky, det_kx]`` and routinely
exceeds RAM, so this module never accepts (or materializes) the whole
cube. Instead it consumes an iterable of ``(row_start, block)`` pairs —
the protocol a lazy dataset's ``iter_scan_rows()`` is expected to yield
(see ``virtual_detector`` for the exact shape contract). This module does
NOT import that dataset class — it is built in a parallel module — so it
stays a standalone pure-math layer the route layer wires up later.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
from numpy.typing import DTypeLike

from fermiviewer.calc.fourd.geometry import aperture_mask

__all__ = [
    "virtual_detector",
    "bf_mask",
    "adf_mask",
    "abf_mask",
    "com_shift_maps",
]


def virtual_detector(
    blocks: Iterable[tuple[int, np.ndarray]],
    mask: np.ndarray,
    out_dtype: DTypeLike = np.float64,
) -> np.ndarray:
    """Integrate a reciprocal-space ``mask`` over every probe position.

    ``blocks`` yields ``(row_start, block)`` pairs:

      - ``row_start``: int, 0-based scan-row offset of ``block`` within
        the full scan.
      - ``block``: ndarray of shape ``(rows, scan_x, det_ky, det_kx)`` —
        a contiguous run of ``rows`` scan rows, full scan width, full
        detector frame, in whatever dtype the dataset stores (uint8/16,
        float32, ...). Blocks may be any size (including 1 row) and are
        consumed one at a time; together they must cover every scan row
        exactly once for a complete map.

    ``mask`` is boolean (see ``geometry.aperture_mask``) or float — a
    non-boolean mask is used as-is as per-pixel weights, which lets a
    soft-edged aperture be integrated the same way.

    Peak memory is one block plus the small ``(rows, scan_x)`` reduction
    of it — the full cube is never resident. Each block's reduction
    (``np.tensordot`` contracting the two detector axes) is accumulated
    into a list of small ``(row_start, reduced)`` pieces — never the full
    block — and stitched into the output map once every block has been
    consumed, so a one-pass (generator) ``blocks`` iterable works.

    Returns a ``(scan_y, scan_x)`` array of dtype ``out_dtype``, computed
    in float64 internally regardless of the input dtype.
    """
    mask_f = np.asarray(mask, dtype=np.float64)
    pieces: list[tuple[int, np.ndarray]] = []
    scan_x: int | None = None
    max_row = 0

    for row_start, block in blocks:
        block = np.asarray(block)
        rows = block.shape[0]
        if scan_x is None:
            scan_x = block.shape[1]
        reduced = np.tensordot(block, mask_f, axes=([2, 3], [0, 1]))
        pieces.append((row_start, np.asarray(reduced, dtype=np.float64)))
        max_row = max(max_row, row_start + rows)

    if scan_x is None:
        return np.zeros((0, 0), dtype=out_dtype)

    out = np.zeros((max_row, scan_x), dtype=out_dtype)
    for row_start, reduced in pieces:
        out[row_start : row_start + reduced.shape[0]] = reduced
    return out


def bf_mask(
    det_shape: tuple[int, int], center: tuple[float, float], semi_angle_px: float
) -> np.ndarray:
    """Bright-field aperture: a disk of radius ``semi_angle_px`` centered
    on the direct (undiffracted) beam."""
    return aperture_mask(det_shape, center, 0.0, semi_angle_px, shape="circle")


def adf_mask(
    det_shape: tuple[int, int],
    center: tuple[float, float],
    inner_px: float,
    outer_px: float,
) -> np.ndarray:
    """(H)ADF aperture: an outer annulus of scattered intensity, conventionally
    with ``inner_px`` at or beyond the bright-field disk radius."""
    return aperture_mask(det_shape, center, inner_px, outer_px, shape="annulus")


def abf_mask(
    det_shape: tuple[int, int],
    center: tuple[float, float],
    inner_px: float,
    outer_px: float,
) -> np.ndarray:
    """ABF aperture: an annulus WITHIN the bright-field disk (typically
    ``inner_px`` around half the BF semi-angle, ``outer_px`` at or inside
    it) — suppresses the direct beam while staying inside the BF cone,
    used for light-element (e.g. H/Li/O) phase-contrast imaging."""
    return aperture_mask(det_shape, center, inner_px, outer_px, shape="annulus")


def com_shift_maps(
    blocks: Iterable[tuple[int, np.ndarray]],
    center: tuple[float, float],
) -> tuple[np.ndarray, np.ndarray]:
    """Per-probe center-of-mass shift relative to ``center``, streamed.

    Same ``(row_start, block)`` protocol as ``virtual_detector``. For
    each diffraction pattern, computes the intensity centroid (first
    moment over the two detector axes) and subtracts ``center`` — the
    center-of-mass STEM-DPC signal (Müller-Caspary et al., "Measurement
    of atomic electric fields and charge densities from average
    momentum transfers using scanning transmission electron
    microscopy", Ultramicroscopy 178 (2017)). Implemented directly from
    that first-moment definition; py4DSTEM/pyxem (AGPL) were not
    consulted.

    A pattern with zero (or non-positive) total intensity contributes a
    shift of 0 at that probe position rather than dividing by zero.

    Returns ``(com_y_shift, com_x_shift)``, each ``(scan_y, scan_x)``.
    """
    cy0, cx0 = center
    pieces_y: list[tuple[int, np.ndarray]] = []
    pieces_x: list[tuple[int, np.ndarray]] = []
    scan_x: int | None = None
    max_row = 0

    for row_start, block in blocks:
        block = np.asarray(block, dtype=np.float64)
        rows = block.shape[0]
        if scan_x is None:
            scan_x = block.shape[1]
        # Recomputed per block (cheap — just two aranges) rather than cached
        # across iterations: keeps the loop free of an Optional local that
        # would otherwise need a redundant not-None assertion on every use.
        det_ky, det_kx = block.shape[2], block.shape[3]
        ys = np.arange(det_ky, dtype=np.float64)[None, :, None]
        xs = np.arange(det_kx, dtype=np.float64)[None, None, :]

        total = block.sum(axis=(2, 3))
        safe_total = np.where(total > 0, total, 1.0)
        com_y = np.where(total > 0, (block * ys).sum(axis=(2, 3)) / safe_total - cy0, 0.0)
        com_x = np.where(total > 0, (block * xs).sum(axis=(2, 3)) / safe_total - cx0, 0.0)
        pieces_y.append((row_start, com_y))
        pieces_x.append((row_start, com_x))
        max_row = max(max_row, row_start + rows)

    if scan_x is None:
        empty = np.zeros((0, 0))
        return empty, empty

    out_y = np.zeros((max_row, scan_x))
    out_x = np.zeros((max_row, scan_x))
    for row_start, piece in pieces_y:
        out_y[row_start : row_start + piece.shape[0]] = piece
    for row_start, piece in pieces_x:
        out_x[row_start : row_start + piece.shape[0]] = piece
    return out_y, out_x
