"""Savitzky-Golay smoothing + derivative for 1-D spectra/profiles (was
audit R5, ANALYSIS_PRESENTATION_PLAN.md #5).

Thin, validated wrapper around ``scipy.signal.savgol_filter`` — the
filter itself is not hand-rolled here (a hand-rolled least-squares
polynomial filter is exactly the kind of mistake this delegates to a
well-tested library instead of risking). Both functions:

- fit a degree-``polyorder`` polynomial over a sliding ``window``-wide
  neighbourhood by least squares, and evaluate that polynomial (or one
  of its derivatives) at the window's centre — the classic
  Savitzky-Golay construction (Savitzky & Golay, *Anal. Chem.* 1964).
- accept a single 1-D array only; a caller with a spectrum-image cube
  must reduce it to one trace (e.g. ``DataStruct.sum_spectrum()``)
  before calling in — see ``ops/catalogue_spectral.py``'s ``savgol``/
  ``savgol_derivative`` ops for that reduction policy.
- return ``float64`` regardless of the input dtype.

The defining property of a Savitzky-Golay smooth (unlike a box or
Gaussian moving average) is that it reproduces any polynomial of degree
<= ``polyorder`` exactly in the interior of the array — this is what
lets it flatten noise without eroding sharp peak shapes the way a
plain moving average does. ``tests/test_smoothing.py`` pins that
property directly.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import savgol_filter

__all__ = ["savgol_derivative", "savgol_smooth"]


def _validate(
    y: np.ndarray, window: int, polyorder: int, order: int | None = None
) -> np.ndarray:
    y = np.asarray(y, dtype=np.float64)
    if y.ndim != 1:
        raise ValueError(f"savgol filter requires a 1-D array, got {y.ndim}D")
    if window % 2 == 0:
        raise ValueError(f"window must be odd, got {window}")
    if window <= polyorder:
        raise ValueError(f"window ({window}) must be > polyorder ({polyorder})")
    if window > y.size:
        raise ValueError(f"window ({window}) must be <= len(y) ({y.size})")
    if order is not None and not (1 <= order <= polyorder):
        raise ValueError(
            f"order ({order}) must satisfy 1 <= order <= polyorder ({polyorder})"
        )
    return y


def savgol_smooth(y: np.ndarray, *, window: int, polyorder: int) -> np.ndarray:
    """Savitzky-Golay smoothing of a 1-D trace.

    At each point, fits a degree-``polyorder`` polynomial by least
    squares over the ``window``-wide neighbourhood centred on it and
    replaces the value with the fitted polynomial's value there
    (``scipy.signal.savgol_filter`` with ``deriv=0``). Edge points (fewer
    than ``window // 2`` neighbours on one side) use ``scipy``'s
    ``mode="interp"`` edge handling: the fit from the nearest full
    window is extrapolated to them.

    Parameters
    ----------
    y : ndarray, shape (n,)
        Trace to smooth (spectrum counts, line profile, etc.).
    window : int
        Filter window length in samples. Must be odd and <= ``len(y)``.
    polyorder : int
        Degree of the fitted polynomial. Must be < ``window``.

    Returns
    -------
    ndarray, shape (n,), float64
        The smoothed trace.

    Raises
    ------
    ValueError
        If ``y`` is not 1-D, ``window`` is even, ``window <= polyorder``,
        or ``window > len(y)``.

    Examples
    --------
    >>> import numpy as np
    >>> x = np.linspace(0, 10, 200)
    >>> y = x**2 + np.random.default_rng(0).normal(scale=0.5, size=x.size)
    >>> smoothed = savgol_smooth(y, window=11, polyorder=3)
    >>> smoothed.shape
    (200,)
    """
    y = _validate(y, window, polyorder)
    out = savgol_filter(y, window_length=window, polyorder=polyorder)
    return np.asarray(out, dtype=np.float64)


def savgol_derivative(
    y: np.ndarray,
    *,
    window: int,
    polyorder: int,
    order: int = 1,
    delta: float = 1.0,
) -> np.ndarray:
    """Savitzky-Golay derivative of a 1-D trace.

    Same local polynomial fit as ``savgol_smooth``, but evaluates the
    fitted polynomial's ``order``-th derivative instead of its value.
    ``delta`` is the (assumed-uniform) spacing between samples on the
    trace's own axis, so the returned derivative is already in units of
    "y per axis unit" (e.g. counts/eV for an energy axis with a 1 eV/
    channel scale) rather than "y per channel". Passing ``delta=1.0``
    (the default) returns the per-channel derivative.

    Parameters
    ----------
    y : ndarray, shape (n,)
        Trace to differentiate.
    window : int
        Filter window length in samples. Must be odd and <= ``len(y)``.
    polyorder : int
        Degree of the fitted polynomial. Must be < ``window``.
    order : int, default 1
        Derivative order. Must satisfy ``1 <= order <= polyorder`` (a
        degree-``polyorder`` polynomial has no well-defined derivative
        above its own degree).
    delta : float, default 1.0
        Sample spacing on the trace's axis (same units the axis is
        calibrated in). Must be finite and nonzero.

    Returns
    -------
    ndarray, shape (n,), float64
        The ``order``-th derivative trace.

    Raises
    ------
    ValueError
        If ``y`` is not 1-D, ``window`` is even, ``window <= polyorder``,
        ``window > len(y)``, ``order`` is outside ``[1, polyorder]``, or
        ``delta`` is not finite/nonzero.

    Examples
    --------
    >>> import numpy as np
    >>> x = np.linspace(0, 10, 200)
    >>> dx = x[1] - x[0]
    >>> y = x**2
    >>> dydx = savgol_derivative(y, window=11, polyorder=3, order=1, delta=dx)
    >>> np.allclose(dydx[20:-20], 2 * x[20:-20], atol=1e-6)
    True
    """
    y = _validate(y, window, polyorder, order)
    if not np.isfinite(delta) or delta == 0:
        raise ValueError(f"delta must be finite and nonzero, got {delta}")
    out = savgol_filter(
        y, window_length=window, polyorder=polyorder, deriv=order, delta=delta
    )
    return np.asarray(out, dtype=np.float64)
