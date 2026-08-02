"""FourDDataset — the lazy 4D-STEM data model (PLAN_4DSTEM #1, ADR 0001).

A 4D-STEM acquisition is ``(scan_y, scan_x, det_ky, det_kx)``: one full
diffraction pattern per scanned probe position. These cubes are large enough
(a modest 256x256 scan of a 256x256 detector at uint16 is 8 GiB) that the
existing :class:`~fermiviewer.datastruct.DataStruct` contract — which
freezes its *entire* buffer eagerly in ``__post_init__`` and caps at 3D — is
the wrong fit. ``FourDDataset`` is therefore a deliberately SEPARATE class
(see ``docs/adr/0001-fourd-data-model.md`` for the full rationale): it never
materializes the whole cube, only ever holding one diffraction pattern or one
block of scan rows in memory at a time.

Design:
    * ``handle`` is a backend-owned, lazily-indexable object (an ``h5py.
      Dataset`` for HyperSpy-4D files, or a small memmap-backed accessor for
      MIB — see ``io/fourd/``) supporting two access patterns:
        - ``handle[y, x]``      -> single pattern, shape == det_shape
        - ``handle[row0:row1]`` -> block, shape (row1-row0, scan_x, *det_shape)
      Nothing in this module ever indexes the handle with anything else, so
      any object implementing just those two slice forms works.
    * Per-axis calibration reuses :class:`~fermiviewer.datastruct.AxisCal`
      (already a pure, frozen value type) rather than inventing a parallel
      calibration model.
    * ``nav_image`` (sum over the detector, one value per scan position) and
      ``mean_pattern`` (mean over the scan, one full pattern) are the two
      reductions every 4D-STEM workflow needs first; both are computed by
      streaming ``iter_scan_rows`` once and cached on the instance — repeat
      access is free, but the FIRST access still touches the whole cube (it
      has to, to sum/average it) at ``block_rows``-at-a-time memory cost, not
      whole-cube cost.

Downstream products of a FourDDataset (the nav image, virtual/annular
detector maps, an averaged pattern) are ordinary 2D DataStructs — they get
registered in the normal image SessionStore and flow through the existing
render/measure/export pipeline unchanged. Only the raw 4D cube itself lives
behind this lazy wrapper.

Pure-library module: numpy + datastruct only (layering guard applies).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any, Protocol, runtime_checkable

import numpy as np

from fermiviewer.datastruct import AxisCal

__all__ = ["FourDDataset", "FourDHandle"]


@runtime_checkable
class FourDHandle(Protocol):
    """Minimal indexing contract a FourDDataset's backend must satisfy.

    ``key`` is either a ``(y, x)`` tuple of ints (one pattern) or a plain
    ``slice`` over scan rows (a block). Implementations own the real file
    resource (an open ``h5py.File`` / ``np.memmap``) and must NEVER return
    something that required loading the whole cube to produce.
    """

    def __getitem__(self, key: Any) -> np.ndarray: ...


# One row-block at a time by default: for a 512x512 uint8 Merlin detector
# and a scan a few hundred columns wide, 8 rows is a few tens of MB — small
# relative to the multi-GB whole cube it's standing in for. Callers with a
# much bigger detector (e.g. a 4k direct-electron camera) should pass a
# smaller `block_rows` to `iter_scan_rows`.
_DEFAULT_BLOCK_ROWS = 8


class FourDDataset:
    """Lazy 4D-STEM dataset: ``(scan_y, scan_x, det_ky, det_kx)``.

    Never loads the whole cube. ``pattern()`` reads one diffraction pattern;
    ``iter_scan_rows()`` streams row-blocks; ``nav_image``/``mean_pattern``
    are cached reductions computed by streaming those blocks exactly once.

    Worst-case RAM for any one reduction/route touching this dataset is
    ``block_rows * scan_cols * det_ky * det_kx * itemsize`` bytes (one
    in-flight block) plus, for ``nav_image``, the ``scan_y * scan_x`` float64
    output array (negligible next to the cube) — see callers in
    ``routes/fourd.py`` for the concrete numbers per route.
    """

    def __init__(
        self,
        handle: FourDHandle,
        scan_shape: tuple[int, int],
        det_shape: tuple[int, int],
        scan_axes: tuple[AxisCal, AxisCal],
        det_axes: tuple[AxisCal, AxisCal],
        dtype: np.dtype[Any] | str,
        metadata: dict[str, Any] | None = None,
        *,
        close_fn: Callable[[], None] | None = None,
        block_rows: int = _DEFAULT_BLOCK_ROWS,
    ) -> None:
        if scan_shape[0] <= 0 or scan_shape[1] <= 0:
            raise ValueError(f"scan_shape must be positive, got {scan_shape}")
        if det_shape[0] <= 0 or det_shape[1] <= 0:
            raise ValueError(f"det_shape must be positive, got {det_shape}")
        if len(scan_axes) != 2 or len(det_axes) != 2:
            raise ValueError("scan_axes and det_axes must each have exactly 2 entries")
        self._handle = handle
        self.scan_shape = (int(scan_shape[0]), int(scan_shape[1]))
        self.det_shape = (int(det_shape[0]), int(det_shape[1]))
        self.scan_axes = scan_axes
        self.det_axes = det_axes
        self.dtype = np.dtype(dtype)
        self.metadata: dict[str, Any] = dict(metadata or {})
        self._close_fn = close_fn
        self.block_rows = max(1, int(block_rows))
        self._nav_image: np.ndarray | None = None
        self._mean_pattern: np.ndarray | None = None

    # ── single-pattern / block access ─────────────────────────────────
    def pattern(self, y: int, x: int) -> np.ndarray:
        """One diffraction pattern at scan position (y, x), shape det_shape."""
        rows, cols = self.scan_shape
        if not (0 <= y < rows and 0 <= x < cols):
            raise IndexError(
                f"scan position ({y}, {x}) outside scan_shape {self.scan_shape}"
            )
        return np.asarray(self._handle[int(y), int(x)])

    def iter_scan_rows(
        self, block_rows: int | None = None
    ) -> Iterator[tuple[int, np.ndarray]]:
        """Yield ``(row_start, block)`` for consecutive scan-row blocks.

        ``block`` has shape ``(n_rows, scan_x, det_ky, det_kx)`` where
        ``n_rows <= block_rows`` (the last block may be shorter). Never
        materializes more than one block at a time.
        """
        rows, _cols = self.scan_shape
        step = max(1, int(block_rows)) if block_rows is not None else self.block_rows
        for row0 in range(0, rows, step):
            row1 = min(row0 + step, rows)
            yield row0, np.asarray(self._handle[row0:row1])

    # ── cached streamed reductions ─────────────────────────────────────
    @property
    def nav_image(self) -> np.ndarray:
        """Navigation image: detector-summed intensity per scan position.

        Computed once (streaming ``iter_scan_rows``) and cached; shape ==
        scan_shape, dtype float64.
        """
        if self._nav_image is None:
            self._nav_image = self._compute_nav_image()
        return self._nav_image

    def _compute_nav_image(self) -> np.ndarray:
        rows, cols = self.scan_shape
        out = np.empty((rows, cols), dtype=np.float64)
        for row0, block in self.iter_scan_rows():
            out[row0 : row0 + block.shape[0]] = np.sum(
                block, axis=(2, 3), dtype=np.float64
            )
        return out

    @property
    def mean_pattern(self) -> np.ndarray:
        """Scan-averaged diffraction pattern; shape == det_shape, float64."""
        if self._mean_pattern is None:
            self._mean_pattern = self._compute_mean_pattern()
        return self._mean_pattern

    def _compute_mean_pattern(self) -> np.ndarray:
        acc = np.zeros(self.det_shape, dtype=np.float64)
        rows, cols = self.scan_shape
        for _row0, block in self.iter_scan_rows():
            acc += np.sum(block, axis=(0, 1), dtype=np.float64)
        n = rows * cols
        return acc / n if n else acc

    # ── lifecycle ────────────────────────────────────────────────────
    def close(self) -> None:
        """Release the underlying file handle (h5py.File.close / memmap)."""
        if self._close_fn is not None:
            self._close_fn()

    def __enter__(self) -> FourDDataset:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
