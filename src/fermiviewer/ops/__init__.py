"""Operation vocabulary — the shared step layer for scripting, batch, and
provenance (Scripting #1). Importing the package registers the catalogue.

Pure layer (no fastapi/pydantic) — usable headless from `fermiviewer.api`.
"""

from __future__ import annotations

from fermiviewer.ops import catalogue  # noqa: F401  (import registers ops)
from fermiviewer.ops.base import OpParam, OpResult, OpSpec, ParamError
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
    "register",
    "run",
]
