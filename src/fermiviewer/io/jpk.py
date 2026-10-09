"""JPK Instruments (Bruker) AFM images: .jpk and .jpk-qi-image.

A JPK image is a multi-page TIFF. Page 0 is a thumbnail; every further
page is one channel of raw integers plus private tags (JPKImageSpec 2.0):

* 32834/32835 — scan size along the fast/slow axis (m); 32838/32839 —
  pixels along them.
* 32848 — channel name, 32849 — retrace flag, 32850 — display name.
* 32896 — number of calibration slots, 32897 — the default slot's name.
* Slots are 48 tags apart from 32912: +0 slot name, +18 (32930) unit,
  +19 scaling type, +20 multiplier, +21 offset. A ``LinearScaling`` slot
  converts the RAW integers directly (the factors are pre-composed along
  the slot chain), so the default slot's multiplier and offset give the
  calibrated values.

Lines are stored bottom to top, so rows are flipped to put the top row
first — the same convention ``io/nanoscope.py`` follows.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from fermiviewer.datastruct import DataStruct
from fermiviewer.io.spm_common import primary_channel, spm_channel, unique_labels

__all__ = ["JpkError", "load_jpk", "load_jpk_all"]

_ULEN, _VLEN, _ILEN, _JLEN = 32834, 32835, 32838, 32839
_CHANNEL, _RETRACE, _FANCY = 32848, 32849, 32850
_N_SLOTS, _DEFAULT_SLOT = 32896, 32897
_SLOT0, _SLOT_STRIDE = 32912, 48
_UNIT, _SCALING, _MULT, _OFFSET = 18, 19, 20, 21    # offsets within a slot


class JpkError(ValueError):
    """Not a readable JPK image."""


def _tag(page: Any, code: int) -> Any:
    tag = page.tags.get(code)
    return None if tag is None else tag.value


def _scaling(page: Any) -> tuple[float, float, str]:
    """(multiplier, offset, unit) of the default calibration slot."""
    default = _tag(page, _DEFAULT_SLOT)
    n = int(_tag(page, _N_SLOTS) or 0)
    for k in range(n):
        base = _SLOT0 + k * _SLOT_STRIDE
        if _tag(page, base) != default:
            continue
        if _tag(page, base + _SCALING) != "LinearScaling":
            break                                        # raw slot: no scaling
        return (float(_tag(page, base + _MULT)), float(_tag(page, base + _OFFSET)),
                str(_tag(page, base + _UNIT) or ""))
    return 1.0, 0.0, ""


def load_jpk_all(path: str | Path) -> list[DataStruct]:
    """Every channel page of the file as a calibrated image."""
    import tifffile

    try:
        tif = tifffile.TiffFile(path)
    except (tifffile.TiffFileError, ValueError) as e:
        raise JpkError(f"not a JPK image: {e}") from None
    out = []
    with tif:
        pages = list(tif.pages)
        if not pages or _tag(pages[0], _ULEN) is None:
            raise JpkError("not a JPK image (no JPK scan tags)")
        for page in pages[1:]:
            name = _tag(page, _CHANNEL)
            if name is None:
                continue
            raw = page.asarray()
            if raw.ndim != 2:
                continue
            mult, off, unit = _scaling(page)
            ny, nx = raw.shape
            ulen = float(_tag(page, _ULEN) or _tag(pages[0], _ULEN) or np.nan)
            vlen = float(_tag(page, _VLEN) or _tag(pages[0], _VLEN) or np.nan)
            retrace = bool(_tag(page, _RETRACE))
            fancy = str(_tag(page, _FANCY) or name)
            direction = "retrace" if retrace else "trace"
            out.append(spm_channel(
                np.flipud(raw.astype(np.float64) * mult + off),
                parser="jpk", channel=fancy, label=f"{fancy} ({direction})",
                value_unit=unit, dy_nm=vlen * 1e9 / ny, dx_nm=ulen * 1e9 / nx,
                line_direction=direction, jpk_channel=str(name),
            ))
    if not out:
        raise JpkError("the file holds no image channels")
    # trace channels before retrace ones, so a plain open shows the trace
    return unique_labels(sorted(out, key=lambda ds: ds.metadata["line_direction"] != "trace"))


def load_jpk(path: str | Path) -> DataStruct:
    """The topography channel (height trace, or the first one)."""
    return primary_channel(load_jpk_all(path))
