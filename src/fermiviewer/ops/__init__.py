"""Operation vocabulary — the shared step layer for scripting, batch, and
provenance (Scripting #1). Importing the package registers the catalogue.

Pure layer (no fastapi/pydantic) — usable headless from `fermiviewer.api`.
"""

from __future__ import annotations

from fermiviewer.ops import (
    catalogue,  # noqa: F401  (import registers ops)
    catalogue_analysis,  # noqa: F401  (model-fit + distribution ops)
    catalogue_atoms_defects,  # noqa: F401  (wave B: atoms/template/defect ops)
    catalogue_diffraction,  # noqa: F401  (wave C: detect/calibrate/simulate ops)
    catalogue_fourier,  # noqa: F401  (wave B: FFT/VDF/GPA/lattice/CTF ops)
    catalogue_grains_layers,  # noqa: F401  (wave A: grain + layer ops)
    catalogue_spectral,  # noqa: F401  (EELS/EDS/diffraction ops)
    catalogue_structure,  # noqa: F401  (wave A: particle/region ops)
)
from fermiviewer.ops.base import (
    OpParam,
    OpResult,
    OpSpec,
    ParamError,
    produces_value_result,
)
from fermiviewer.ops.registry import (
    UnknownOpError,
    get_spec,
    list_ops,
    register,
    run,
)

__all__ = [
    "OpParam",
    "OpResult",
    "OpSpec",
    "ParamError",
    "UnknownOpError",
    "get_spec",
    "list_ops",
    "produces_value_result",
    "register",
    "run",
]
