"""Parser registry — single-registration extension dispatch.

One map, one registration per parser (the deliberate improvement over the
MATLAB dual-registration). Ambiguous extensions get content sniffers when
they arrive (e.g. .dat).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fermiviewer.datastruct import DataStruct
from fermiviewer.io.bcf import load_bcf
from fermiviewer.io.dm import load_dm

__all__ = ["UnsupportedFormatError", "load_auto", "supported_extensions"]


class UnsupportedFormatError(ValueError):
    pass


_LOADERS: dict[str, Callable[[Path], DataStruct]] = {
    ".dm3": load_dm,
    ".dm4": load_dm,
    ".bcf": load_bcf,
    # .ser / .mrc / .tif / … register here as they port (W2)
}


def supported_extensions() -> tuple[str, ...]:
    return tuple(sorted(_LOADERS))


def load_auto(path: str | Path) -> DataStruct:
    p = Path(path)
    loader = _LOADERS.get(p.suffix.lower())
    if loader is None:
        raise UnsupportedFormatError(
            f"no parser for '{p.suffix}' (supported: {', '.join(supported_extensions())})"
        )
    return loader(p)
