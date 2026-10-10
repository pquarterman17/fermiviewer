"""Analyse many force curves (a force map) across processes.

Each curve's fit is a small scipy least-squares problem — a few ms, most of
it Python overhead the GIL serialises — so threads gain nothing and the
curves are split across a process pool instead. Below ``PARALLEL_MIN``
curves, or with one CPU, it runs in-process: starting spawn workers (each
re-imports numpy/scipy) costs more than it saves. Results are the same
either way, curve for curve.

The pool uses the ``spawn`` start method on every platform: forking a
threaded server can deadlock, and spawn is what macOS and Windows use
anyway. A packaged (PyInstaller) build needs ``multiprocessing.
freeze_support()`` in its entry point for that (tools/bundle/fv_entry.py);
should the pool still fail to start, the curves are analysed in-process.
"""

from __future__ import annotations

import multiprocessing
import os
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import Any

import numpy as np

from fermiviewer.calc.afm_force import ForceAnalysis, analyze_curve

__all__ = ["CurveArrays", "PARALLEL_MIN", "analyze_curves"]

#: (approach Z, approach deflection, retract Z | None, retract deflection | None), nm
CurveArrays = tuple[np.ndarray, np.ndarray, np.ndarray | None, np.ndarray | None]

PARALLEL_MIN = 200          # curves; fewer run in-process
_MAX_WORKERS = 8


def _one(curve: CurveArrays, options: dict[str, Any]) -> ForceAnalysis | None:
    try:
        return analyze_curve(*curve, **options)
    except (ValueError, np.linalg.LinAlgError):
        return None                     # an unusable curve is a gap in the map


def _chunk(curves: Sequence[CurveArrays], options: dict[str, Any]) -> list[ForceAnalysis | None]:
    return [_one(c, options) for c in curves]


def _workers() -> int:
    return min(os.cpu_count() or 1, _MAX_WORKERS)


def analyze_curves(curves: Sequence[CurveArrays], *, parallel: bool | None = None,
                   **options: Any) -> list[ForceAnalysis | None]:
    """`analyze_curve` over every curve, in order; None where a curve fails.

    `parallel` None decides by size and CPU count; True / False force it."""
    n = _workers()
    if parallel is None:
        parallel = len(curves) >= PARALLEL_MIN and n > 1
    if not parallel or not curves:
        return _chunk(curves, options)
    size = -(-len(curves) // (n * 4))   # ~4 chunks per worker evens out the load
    chunks = [curves[i:i + size] for i in range(0, len(curves), size)]
    try:
        with ProcessPoolExecutor(max_workers=n,
                                 mp_context=multiprocessing.get_context("spawn")) as pool:
            parts = list(pool.map(_chunk, chunks, [options] * len(chunks)))
    except (BrokenProcessPool, OSError):
        return _chunk(curves, options)
    return [r for part in parts for r in part]
