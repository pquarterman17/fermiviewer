"""Regression tests for edge-case crashes found by fuzzing the backend."""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.atoms import fit_gaussian_2d
from fermiviewer.calc.defects import _otsu_threshold
from fermiviewer.calc.filters import clahe
from fermiviewer.calc.radial import azimuthal_integrate


def test_azimuthal_too_small_is_value_error() -> None:
    # 1-row crops / line scans gave n_bins = 0 → ZeroDivisionError (500)
    with pytest.raises(ValueError):
        azimuthal_integrate(np.ones((1, 50)))


def test_atom_fit_skips_non_finite_window() -> None:
    yy, xx = np.mgrid[0:32, 0:32]
    img = np.exp(-((xx - 16) ** 2 + (yy - 16) ** 2) / 8.0)
    img[15, 15] = np.inf  # used to trip `assert f is not None`
    fit = fit_gaussian_2d(img, np.array([[17.0, 17.0]]))
    assert not fit.converged[0]


def test_clahe_with_nan_pixels() -> None:
    img = np.random.default_rng(0).random((64, 64))
    img[3, 3] = np.nan
    out = clahe(img)
    assert out.shape == img.shape


def test_otsu_ignores_nan() -> None:
    r = np.linspace(0, 1, 100)
    r[5] = np.nan
    assert np.isfinite(_otsu_threshold(r))
