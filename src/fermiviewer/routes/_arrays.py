"""Shared ValueError→422 guard.

np.asarray on malformed/ragged request input (and calc-layer shape
validation) raises ValueError — every analysis endpoint should surface
that as a 422, not let it leak out as an unhandled 500.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import HTTPException

__all__ = ["value_error_as_422"]


@contextmanager
def value_error_as_422() -> Iterator[None]:
    try:
        yield
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
