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
    catalogue_eds_calib,  # noqa: F401  (wave D: EDS recalibrate/auto-assign)
    catalogue_eds_model,  # noqa: F401  (wave D: EDS continuum/artifacts/zeta)
    catalogue_eels_advanced,  # noqa: F401  (wave D: KK/SVD/align/deconvolution)
    catalogue_eels_core,  # noqa: F401  (wave D: background/ELNES/auto-assign)
    catalogue_eels_maps,  # noqa: F401  (wave D: thickness/quantify/fit/species maps)
    catalogue_fourier,  # noqa: F401  (wave B: FFT/VDF/GPA/lattice/CTF ops)
    catalogue_grains_edit,  # noqa: F401  (grain label editing)
    catalogue_grains_layers,  # noqa: F401  (wave A: grain + layer ops)
    catalogue_grains_trained,  # noqa: F401  (scribble-trained segmentation)
    catalogue_layers_multi,  # noqa: F401  (multi-map layers + layer grains)
    catalogue_measure,  # noqa: F401  (wave D: profile/ROI/box/distance ops)
    catalogue_measure_reads,  # noqa: F401  (wave D: spectrum/histogram/scalebar)
    catalogue_montage,  # noqa: F401  (montage + physical-scale compare)
    catalogue_shape_strain,  # noqa: F401  (fit-shape + atom-column strain)
    catalogue_spectral,  # noqa: F401  (EELS/EDS/diffraction ops)
    catalogue_stack,  # noqa: F401  (multi-input: image math/align/MIP)
    catalogue_structure,  # noqa: F401  (wave A: particle/region ops)
)
from fermiviewer.ops.base import (
    ANY_SCALAR,
    InputError,
    OpInput,
    OpParam,
    OpResult,
    OpSpec,
    ParamError,
    RecordSpec,
    RingsSpec,
    RowSpec,
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
    "ANY_SCALAR",
    "InputError",
    "OpInput",
    "OpParam",
    "OpResult",
    "OpSpec",
    "ParamError",
    "RecordSpec",
    "RingsSpec",
    "RowSpec",
    "UnknownOpError",
    "get_spec",
    "list_ops",
    "produces_value_result",
    "register",
    "run",
]
