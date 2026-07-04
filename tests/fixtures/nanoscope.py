"""Synthetic Bruker Nanoscope file generator for tests.

Writes a minimal but valid `.spm`: an ASCII CIAO header + one int16 Height
channel, with calibration values chosen so the result is analytically
checkable. Mirrors the ``minisfs`` / ``minidm4`` fixture pattern.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

# Method-A calibration the fixture encodes:
#   z_scale = hard_scale × sensitivity = 0.001 V/LSB × 100 nm/V = 0.1 nm/LSB
#   lateral = 100 nm / 4 px = 25 nm/px
_HARD_SCALE = 0.001  # V/LSB, from the (…) parenthetical
_SENS = 100.0  # nm/V, the Sens. Zsens hard value
_SCAN_NM = 100.0
_NX = _NY = 4
_OFFSET = 4096


def write_nanoscope(
    path: Path,
    *,
    scan_size_key: str = "Scan Size",
    scan_size_value: str = "100e-009 100e-009 m",
    extra_channel: str | None = None,
) -> dict[str, Any]:
    """Write a 4×4 single-channel Height file; return expected values.

    ``scan_size_key`` / ``scan_size_value`` let tests exercise header
    spelling variants (legacy lowercase ``Scan size``, ``~m`` microns).
    ``extra_channel``, if given, appends a second image whose Z-scale
    hard-scale unit is that string (e.g. ``"Arb/LSB"``) so unit-derivation
    can be checked; the second channel reuses the same data block.
    """
    bpp = 2
    # raw LSB values 1..16 in display order (row-major, top-to-bottom)
    display = np.arange(1, _NX * _NY + 1, dtype="<i2").reshape(_NY, _NX)
    stored = np.flipud(display)  # file stores rows bottom-to-top

    extra = ""
    if extra_channel is not None:
        # a second channel is its OWN `\*Ciao image list` section (that is
        # how real multi-channel files are laid out); it reuses the same
        # data block via an identical Data offset
        extra = (
            "\\*Ciao image list\r\n"
            f"\\Data offset: {_OFFSET}\r\n"
            f"\\Data length: {_NX * _NY * bpp}\r\n"
            f"\\Bytes/pixel: {bpp}\r\n"
            f"\\Samps/line: {_NX}\r\n"
            f"\\Number of lines: {_NY}\r\n"
            '\\@2:Image Data: S [Other] "Other"\r\n'
            f"\\@2:Z scale: V [Sens. Other] (0.01 {extra_channel}) 100.0 V\r\n"
        )

    header = (
        "\\*File list\r\n"
        "\\Version: 0x07300000\r\n"  # < 0x09200000 → 16-bit
        "\\*Scanner list\r\n"
        f"\\@Sens. Zsens: V [ZsensSens] (1 nm/V) {_SENS:g} nm/V\r\n"
        "\\@Sens. Other: V [OtherSens] (1 nm/V) 1 nm/V\r\n"
        "\\*Ciao scan list\r\n"
        f"\\{scan_size_key}: {scan_size_value}\r\n"
        f"\\Samps/line: {_NX}\r\n"
        f"\\Number of lines: {_NY}\r\n"
        "\\*Ciao image list\r\n"
        f"\\Data offset: {_OFFSET}\r\n"
        f"\\Data length: {_NX * _NY * bpp}\r\n"
        f"\\Bytes/pixel: {bpp}\r\n"
        f"\\Samps/line: {_NX}\r\n"
        f"\\Number of lines: {_NY}\r\n"
        '\\@2:Image Data: S [ZSensor] "ZSensor"\r\n'
        f"\\@2:Z scale: V [Sens. Zsens] ({_HARD_SCALE:g} V/LSB) 440.0 V\r\n"
        + extra
        + "\\*File list end\r\n"
        "\x1a"
    )
    head = header.encode("latin-1")
    pad = b"\x00" * (_OFFSET - len(head))
    path.write_bytes(head + pad + stored.tobytes())

    z_scale = _HARD_SCALE * _SENS
    return {
        "nx": _NX,
        "ny": _NY,
        "z_scale_nm_per_lsb": z_scale,  # 0.1
        "nm_per_px": _SCAN_NM / _NX,  # 25.0
        "value_unit": "nm",
        "channel": "ZSensor",
        # display[0,0] == 1 LSB → 0.1 nm after calibration
        "expected_top_left_nm": 1 * z_scale,
        "expected_data_nm": display.astype(np.float64) * z_scale,
    }
