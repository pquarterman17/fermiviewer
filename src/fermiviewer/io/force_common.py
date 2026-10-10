"""AFM force curves: the vendor-neutral model the force readers fill.

A force curve is the cantilever deflection recorded while the Z piezo
drives the tip toward the sample (approach / extend) and away again
(retract), optionally with a dwell in between. Readers deliver, per
segment, the Z position and the deflection in time order; ``ForceCurve``
then fixes the two sign conventions every analysis assumes:

* Z increases toward the sample (so the approach runs to larger Z) —
  the approach defines the direction, so a Z recorded the other way is
  negated (``metadata["z_flipped"]``), and
* deflection is positive when the tip is pushed away (repulsive contact),
  as Bruker, Asylum and Nanosurf all record it. It is not guessed from the
  data: on a stiff sample the contact is a few points after a long
  attractive approach, and no heuristic tells that apart from a flip.

Lengths are nm. Deflection is in nm when the file calibrates it, else in V
(``deflection_unit``) and the inverse optical lever sensitivity (InvOLS,
nm/V) converts it; the spring constant (N/m) turns nm into nN.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

__all__ = ["ForceCurve", "ForceError", "ForceFile", "ForceSegment"]


class ForceError(ValueError):
    """Not a readable force-curve file."""


@dataclass
class ForceSegment:
    kind: str                   # "approach" | "retract" | "dwell"
    z: np.ndarray               # nm, time order
    deflection: np.ndarray      # deflection_unit of the file, time order

    def __post_init__(self) -> None:
        self.z = np.asarray(self.z, dtype=np.float64)
        self.deflection = np.asarray(self.deflection, dtype=np.float64)
        keep = np.isfinite(self.z) & np.isfinite(self.deflection)
        self.z, self.deflection = self.z[keep], self.deflection[keep]


@dataclass
class ForceCurve:
    segments: list[ForceSegment]
    label: str = ""
    position_nm: tuple[float, float] | None = None      # (x, y) on a force map
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.segments = [s for s in self.segments if s.z.size >= 2]
        if self.approach is None or self.approach.z.size < 8:
            raise ForceError(f"{self.label or 'curve'}: no approach segment")
        self._orient()

    def segment(self, kind: str) -> ForceSegment | None:
        return next((s for s in self.segments if s.kind == kind), None)

    @property
    def approach(self) -> ForceSegment | None:
        return self.segment("approach")

    @property
    def retract(self) -> ForceSegment | None:
        return self.segment("retract")

    def _orient(self) -> None:
        a = self.approach
        assert a is not None
        if a.z[-1] < a.z[0]:                     # approach must move to larger Z
            for s in self.segments:
                s.z = -s.z
            self.metadata["z_flipped"] = True


@dataclass
class ForceFile:
    curves: list[ForceCurve]
    parser: str
    deflection_unit: str = "nm"                 # "nm" or "V"
    spring_constant: float = float("nan")       # N/m, from the file
    invols: float = float("nan")                # nm/V, from the file
    z_source: str = ""                          # e.g. "Z sensor", "piezo ramp"
    grid: tuple[int, int] | None = None         # (rows, cols) of a force map
    map_pitch_nm: tuple[float, float] | None = None  # (dy, dx) between map points
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.curves:
            raise ForceError("the file holds no force curves")
        if self.grid is not None and self.grid[0] * self.grid[1] != len(self.curves):
            self.grid = None                    # an incomplete map is a list
        if self.grid is None:
            self.map_pitch_nm = None
