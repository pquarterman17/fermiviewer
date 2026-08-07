"""TIFF, common raster images, and headerless RAW.

TIFF maps to tifffile and PNG/JPEG/BMP/GIF to Pillow (sanctioned by the
deps policy — these are container readers, not algorithms). RGB inputs
collapse to grayscale by channel mean (the MATLAB getGrayscale rule);
multi-page TIFFs keep page 0 with n_frames recorded.

A TIFF off an SEM/FIB is not a bare raster: the vendor's whole acquisition
record rides along in a private tag. `io.tiff_meta` reads it, so a Thermo
Fisher dual-beam image opens with its pixel size and stage tilt already
set instead of arriving uncalibrated.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct

__all__ = ["load_image", "load_raw", "load_tiff"]

_RAW_DTYPES = {8: "u1", 16: "u2", 32: "u4"}


def _to_gray(arr: np.ndarray) -> tuple[np.ndarray, bool]:
    if arr.ndim == 3:
        return np.asarray(arr, dtype=np.float64).mean(axis=2), True
    return arr, False


def _image_struct(
    arr: np.ndarray,
    path: Path,
    parser: str,
    axes: tuple[AxisCal, AxisCal] = (AxisCal(), AxisCal()),
    **extra: object,
) -> DataStruct:
    gray, was_rgb = _to_gray(arr)
    bit_depth = arr.dtype.itemsize * 8
    return DataStruct(
        data=gray,
        kind=DataKind.IMAGE,
        axes=axes,
        metadata={
            "source": str(path),
            "parser": parser,
            "bit_depth": bit_depth,
            "was_rgb": was_rgb,
            **extra,
        },
    )


def load_tiff(path: str | Path) -> DataStruct:
    import tifffile

    from fermiviewer.io.tiff_meta import tiff_calibration

    path = Path(path)
    with tifffile.TiffFile(path) as tf:
        n_pages = len(tf.pages)
        arr = tf.pages[0].asarray()
        y_cal, x_cal = AxisCal(), AxisCal()
        cal_meta: dict[str, object] = {}
        try:
            y_cal, x_cal, cal_meta = tiff_calibration(tf, arr.shape)
        except Exception as e:  # noqa: BLE001 - metadata must never block pixels
            warnings.warn(
                f"{path.name}: TIFF metadata unreadable ({type(e).__name__}: {e}); "
                "the image loads uncalibrated",
                stacklevel=2,
            )
    return _image_struct(
        arr, path, "tiff", axes=(y_cal, x_cal), n_frames=n_pages, **cal_meta
    )


def load_image(path: str | Path) -> DataStruct:
    from PIL import Image, UnidentifiedImageError

    path = Path(path)
    try:
        with Image.open(path) as im:
            # palette ("P"), CMYK, YCbCr, LA/PA etc. don't map to meaningful
            # pixel values via np.asarray (a "P" GIF yields palette indices,
            # not colours) — normalise to RGB first; "1" bitmaps to L (0/255).
            # L/I/F and RGB(A) are already intensity/colour, leave them.
            if im.mode == "1":
                arr = np.asarray(im.convert("L"))
            elif im.mode not in ("L", "I", "F", "RGB", "RGBA"):
                arr = np.asarray(im.convert("RGB"))
            else:
                arr = np.asarray(im)
    except UnidentifiedImageError as e:
        raise ValueError(f"unreadable image file: {path}") from e
    if arr.ndim == 3 and arr.shape[2] == 4:  # drop alpha
        arr = arr[:, :, :3]
    return _image_struct(arr, path, "image")


def load_raw(
    path: str | Path,
    width: int,
    height: int,
    bit_depth: int = 16,
    byte_order: str = "little",
    header_bytes: int = 0,
) -> DataStruct:
    """Headerless binary image (explicit geometry — not in load_auto)."""
    path = Path(path)
    if bit_depth not in _RAW_DTYPES:
        raise ValueError(f"bit_depth must be one of {sorted(_RAW_DTYPES)}")
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    bo = "<" if byte_order.startswith("little") else ">"
    dt = np.dtype(f"{bo}{_RAW_DTYPES[bit_depth]}")

    buf = path.read_bytes()[header_bytes:]
    need = width * height * dt.itemsize
    if len(buf) < need:
        raise ValueError(
            f"{path}: expected {need} bytes for {width}x{height}@{bit_depth}-bit, "
            f"found {len(buf)} — check geometry arguments"
        )
    px = np.frombuffer(buf[:need], dtype=dt).reshape(height, width)
    return _image_struct(px, path, "raw")
