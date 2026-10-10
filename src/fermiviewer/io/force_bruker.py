"""Bruker NanoScope force-curve files (``\\*Force file list`` headers).

The header is the CIAO text of the image files (io/nanoscope.py, whose
section parser and channel scaling this reuses); each ``Ciao force image
list`` section is one channel — typically ``Deflection Error`` (nm via
``Sens. DeflSens``) and, on closed-loop scanners, ``Height Sensor`` (nm via
``Sens. ZsensSens``) — holding the extend then the retract curve,
``Samps/line`` points each. Both are stored contact end first: the extend
curve is time-reversed, the retract one in time order.

Values use the hard scale of ``@4:Z scale`` (V/LSB) times the soft scale
(Method A of io/nanoscope.py). On the corpus file the Height Sensor then
spans 592 nm of a 600 nm ramp (``@4:Ramp size`` × ``Sens. Zsens``), which
Gwyddion's extra ×5 for ``ZsensSens`` would break. Without a Height Sensor
channel the Z axis is the nominal ramp, linear in time.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from fermiviewer.io import nanoscope as ns
from fermiviewer.io.force_common import ForceCurve, ForceError, ForceFile, ForceSegment

__all__ = ["is_bruker_force", "load_bruker_force"]

_MAGIC = b"\\*Force file list"


def is_bruker_force(buf: bytes) -> bool:
    return buf.startswith(_MAGIC)


def _ramp_nm(force_list: ns._Section, sens: dict[str, tuple[float, str]]) -> float:
    line = next((b for b in force_list.raw if b.startswith(("@4:Ramp size", "@Ramp size"))), "")
    m = ns._CIAO_V.match(line)
    if not m:
        return float("nan")
    try:
        volts = ns._lead_float(m["value"])
    except (ValueError, IndexError):
        return float("nan")
    soft = (m["soft"] or "Sens. Zsens").strip()
    return volts * sens.get(soft, (float("nan"), ""))[0]


def _channels(buf: bytes, sections: list[ns._Section],
              sens: dict[str, tuple[float, str]]) -> tuple[dict[str, np.ndarray], int, int, str]:
    out: dict[str, np.ndarray] = {}
    n_ext = n_ret = 0
    unit = ""
    for sec in sections:
        if sec.name != "Ciao force image list":
            continue
        try:
            counts = [int(v) for v in sec.kv["Samps/line"].split()]
            offset, length = int(sec.kv["Data offset"]), int(sec.kv["Data length"])
        except (KeyError, ValueError):
            raise ForceError("force channel without Samps/line or data offset") from None
        n_ext, n_ret = counts[0], counts[-1]
        bpp = length // (n_ext + n_ret) if n_ext + n_ret else 0
        if bpp not in (2, 4) or offset + (n_ext + n_ret) * bpp > len(buf):
            raise ForceError("force data does not fit its header (a force volume?)")
        scale, u = ns._z_scale(sec, sens, bpp)
        raw = np.frombuffer(buf, dtype="<i4" if bpp == 4 else "<i2",
                            count=n_ext + n_ret, offset=offset)
        name = ns._channel_name(sec)
        out[name] = raw.astype(np.float64) * scale
        if name.lower().startswith("deflection"):
            unit = u
    return out, n_ext, n_ret, unit


def load_bruker_force(path: str | Path) -> ForceFile:
    buf = Path(path).read_bytes()
    if not is_bruker_force(buf):
        raise ForceError("not a Bruker force file")
    sections = ns._parse_sections(ns._split_header(buf))
    sens = ns._ciao_sensitivities(sections)
    chans, n_ext, n_ret, defl_unit = _channels(buf, sections, sens)
    defl_key = next((k for k in chans if k.lower().startswith("deflection")), None)
    if defl_key is None:
        raise ForceError(f"no deflection channel (have {', '.join(chans) or 'none'})")
    defl = chans[defl_key]
    zkey = next((k for k in chans if k.lower() in ("zsensor", "height sensor")), None)
    if zkey is not None:
        z, z_source = chans[zkey], "Z sensor"
    else:
        force_list = next((s for s in sections if s.name == "Ciao force list"), None)
        ramp = _ramp_nm(force_list, sens) if force_list else float("nan")
        if not np.isfinite(ramp):
            raise ForceError("neither a Height Sensor channel nor a ramp size")
        # index 0 is the contact end of both curves
        z = np.concatenate([np.linspace(ramp, 0, n_ext), np.linspace(ramp, 0, n_ret)])
        z_source = "piezo ramp"
    image_list = next(s for s in sections if s.name == "Ciao force image list")
    try:
        k = float(image_list.kv.get("Spring Constant", "nan"))
    except ValueError:
        k = float("nan")
    defl_sens = sens.get("Sens. DeflSens", (float("nan"), ""))[0]
    curve = ForceCurve([
        ForceSegment("approach", z[:n_ext][::-1], defl[:n_ext][::-1]),
        ForceSegment("retract", z[n_ext:], defl[n_ext:]),
    ], label=Path(path).name)
    return ForceFile(
        [curve], parser="nanoscope", deflection_unit="nm" if defl_unit == "nm" else "V",
        spring_constant=k, invols=defl_sens, z_source=z_source,
        metadata={"channels": list(chans)},
    )
