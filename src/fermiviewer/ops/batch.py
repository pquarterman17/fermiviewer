"""Recipe runner — an ordered list of ops over a DataStruct (Scripting #6).

A *recipe* is a list of ``{"op": name, "params": {...}}`` steps. ``run_recipe``
runs them in order over one input, chaining image-producing steps (each derived
image feeds the next) while value-producing steps (stats/quant) run against the
current image without altering the chain — exactly the macro/batch semantics,
but server-side over the shared op vocabulary.

Pure layer (datastruct/ops/stdlib only). The route + folder-watch (#6/#7) wrap
this with the jobs store; the public façade exposes it as ``Image.pipeline``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fermiviewer.datastruct import DataStruct
from fermiviewer.ops.base import OpResult
from fermiviewer.ops.registry import run

__all__ = ["RecipeResult", "run_recipe", "validate_recipe"]


@dataclass(frozen=True)
class RecipeResult:
    """The outcome of a recipe over one input: every step's OpResult, the
    final chained image (or the input if no image step ran), and just the
    value-producing results for convenient tabular collection."""

    steps: list[OpResult]
    final: DataStruct
    values: list[OpResult]


def validate_recipe(steps: list[dict[str, Any]]) -> None:
    """Cheap structural check before a (possibly long) run: each step is a
    dict with a string ``op``. Param validation happens per-op at run time."""
    for i, step in enumerate(steps):
        if not isinstance(step, dict) or "op" not in step:
            raise ValueError(f"recipe step {i} must be a dict with an 'op' key")
        if not isinstance(step["op"], str):
            raise ValueError(f"recipe step {i}: 'op' must be a string")


def run_recipe(ds: DataStruct, steps: list[dict[str, Any]]) -> RecipeResult:
    """Run an ordered recipe over ``ds``. Image steps chain; value steps run
    against the current chained image. Raises on a bad op/params (the caller
    decides per-input try/continue for multi-input batches)."""
    validate_recipe(steps)
    results: list[OpResult] = []
    values: list[OpResult] = []
    current = ds
    for step in steps:
        result = run(step["op"], current, step.get("params"))
        results.append(result)
        if result.produces_image and result.derived is not None:
            current = result.derived
        else:
            values.append(result)
    return RecipeResult(steps=results, final=current, values=values)
