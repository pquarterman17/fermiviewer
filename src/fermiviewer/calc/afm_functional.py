"""ISO 25178-2 functional parameters, from the areal material ratio curve.

The material ratio curve h(mr) gives, for each material ratio mr (0–100 %),
the height at which that fraction of the surface is material — the heights
sorted from highest to lowest. From it:

* Sk family (ISO 25178-2 § 4.5 / ISO 13565-2): the *equivalent straight
  line* is the secant spanning 40 % of mr with the smallest height drop;
  extended to mr = 0 % and 100 % it gives the core limits. **Sk** is the
  core height between them, **Smr1**/**Smr2** the material ratios where
  the curve crosses those limits, and **Spk**/**Svk** the heights of the
  triangles with the same areas as the peaks above / valleys below the
  core (reduced peak height and reduced valley depth).
* Volume parameters: Vm(p) is the material volume above the height at
  ratio p and Vv(p) the void volume below it, per unit area — so they
  carry the height unit (e.g. nm³/nm² = nm). **Vmp** = Vm(10 %),
  **Vmc** = Vm(80 %) − Vm(10 %), **Vvc** = Vv(10 %) − Vv(80 %),
  **Vvv** = Vv(80 %), the ISO default ratios.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = ["FunctionalParameters", "functional_parameters", "material_ratio_curve"]

_N = 1001          # curve samples, 0.1 % apart
_SECANT = 40.0     # % of material ratio spanned by the equivalent line


def material_ratio_curve(z: np.ndarray, n: int = _N) -> tuple[np.ndarray, np.ndarray]:
    """(mr in %, height) on an even grid of `n` material ratios."""
    h = np.sort(np.asarray(z, dtype=np.float64)[np.isfinite(z)])[::-1]
    if h.size < 2:
        raise ValueError("too few finite pixels for a material ratio curve")
    mr = np.linspace(0.0, 100.0, n)
    src = (np.arange(h.size) + 0.5) / h.size * 100.0       # pixel-centred ratios
    return mr, np.interp(mr, src, h)


@dataclass(frozen=True)
class FunctionalParameters:
    sk: float
    spk: float
    svk: float
    smr1: float     # %
    smr2: float     # %
    vmp: float
    vmc: float
    vvc: float
    vvv: float


def _vm(mr: np.ndarray, h: np.ndarray, p: float) -> float:
    """Material volume per area above the height at ratio p."""
    hp = float(np.interp(p, mr, h))
    sel = mr <= p
    return float(np.trapezoid(np.clip(h[sel] - hp, 0, None), mr[sel]) / 100.0)


def _vv(mr: np.ndarray, h: np.ndarray, p: float) -> float:
    """Void volume per area below the height at ratio p."""
    hp = float(np.interp(p, mr, h))
    sel = mr >= p
    return float(np.trapezoid(np.clip(hp - h[sel], 0, None), mr[sel]) / 100.0)


def functional_parameters(z: np.ndarray, p: float = 10.0, q: float = 80.0) -> FunctionalParameters:
    """Sk family and volume parameters of the (finite) heights in `z`."""
    mr, h = material_ratio_curve(z)
    step = mr[1] - mr[0]
    w = int(round(_SECANT / step))
    drop = h[:-w] - h[w:]                        # height lost across each 40 % window
    i = int(np.argmin(drop))
    slope = -drop[i] / _SECANT                   # height per % (≤ 0)
    hu = h[i] - slope * mr[i]                    # the line at mr = 0 %
    hl = hu + slope * 100.0                      # … and at mr = 100 %
    sk = float(hu - hl)

    above = h > hu                               # peaks (the curve is monotonic)
    below = h < hl
    smr1 = float(np.interp(hu, h[::-1], mr[::-1])) if above.any() else 0.0
    smr2 = float(np.interp(hl, h[::-1], mr[::-1])) if below.any() else 100.0
    a1 = float(np.trapezoid(np.clip(h - hu, 0, None), mr))
    a2 = float(np.trapezoid(np.clip(hl - h, 0, None), mr))
    spk = 2 * a1 / smr1 if smr1 > 0 else 0.0
    svk = 2 * a2 / (100.0 - smr2) if smr2 < 100 else 0.0

    vm_p, vm_q = _vm(mr, h, p), _vm(mr, h, q)
    vv_p, vv_q = _vv(mr, h, p), _vv(mr, h, q)
    return FunctionalParameters(
        sk=sk, spk=spk, svk=svk, smr1=smr1, smr2=smr2,
        vmp=vm_p, vmc=vm_q - vm_p, vvc=vv_p - vv_q, vvv=vv_q,
    )
