"""Recipe runner — an ordered list of ops over a DataStruct (Scripting #6).

A *recipe* is a list of ``{"op": name, "params": {...}}`` steps. ``run_recipe``
runs them in order over one input, chaining image-producing steps (each derived
image feeds the next) while value-producing steps (stats/quant) run against the
current image without altering the chain — exactly the macro/batch semantics,
but server-side over the shared op vocabulary.

A step may also carry ``"inputs": {"<op input>": "<pool name>"}`` for a
multi-input op (ADR 0005 §8). The names are SYMBOLIC: the recipe says "the
second operand is called ``dark``", and the caller binds ``dark`` to an actual
dataset when the recipe runs (``run_recipe(..., inputs={"dark": ds})``). That
indirection is the whole point of a saved recipe — the same steps run over
many subjects in a batch, so an auxiliary dataset cannot be frozen into the
step as a session id, and the pure layer could not resolve such an id anyway.

Pure layer (datastruct/ops/stdlib only). The route + folder-watch (#6/#7) wrap
this with the jobs store; the public façade exposes it as ``Image.pipeline``.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from typing import Any

from fermiviewer.datastruct import DataStruct
from fermiviewer.ops.base import OpResult
from fermiviewer.ops.registry import UnknownOpError, get_spec, run

__all__ = ["RecipeResult", "run_recipe", "step_inputs", "validate_recipe"]


@dataclass(frozen=True)
class RecipeResult:
    """The outcome of a recipe over one input: every step's OpResult, the
    final chained image (or the input if no image step ran), and just the
    value-producing results for convenient tabular collection."""

    steps: list[OpResult]
    final: DataStruct
    values: list[OpResult]


def step_inputs(step: dict[str, Any]) -> dict[str, str]:
    """A step's ``{op input name: pool name}`` map (empty when absent)."""
    return dict(step.get("inputs") or {})


def validate_recipe(
    steps: list[dict[str, Any]], input_names: Collection[str] = ()
) -> None:
    """Cheap structural check before a (possibly long) run: each step is a
    dict with a string ``op``, and every auxiliary input the step names is
    both declared by the op and bound in the run's input pool.

    ``input_names`` is what the caller will supply to ``run_recipe``. Checking
    the references up front is the point: a recipe that names a dataset the
    run cannot provide must fail before the first step, not halfway through a
    200-input batch. Param validation happens per-op at run time.
    """
    available = set(input_names)
    for i, step in enumerate(steps):
        if not isinstance(step, dict) or "op" not in step:
            raise ValueError(f"recipe step {i} must be a dict with an 'op' key")
        if not isinstance(step["op"], str):
            raise ValueError(f"recipe step {i}: 'op' must be a string")
        refs = step.get("inputs")
        if refs is not None and not isinstance(refs, dict):
            raise ValueError(
                f"recipe step {i}: 'inputs' must be a map of "
                f"{{op input name: recipe input name}}"
            )
        try:
            spec = get_spec(step["op"])
        except UnknownOpError:
            continue  # unknown names surface with the registry's own message
        _validate_step_inputs(i, step["op"], spec, step_inputs(step), available)


def _validate_step_inputs(
    i: int, name: str, spec: Any, refs: dict[str, str], available: set[str]
) -> None:
    unknown = set(refs) - set(spec.inputs)
    if unknown:
        raise ValueError(
            f"recipe step {i}: op '{name}' has no auxiliary input(s) "
            f"{sorted(unknown)} (has: {sorted(spec.inputs) or 'none'})"
        )
    for input_name, ref in refs.items():
        if not isinstance(ref, str):
            raise ValueError(
                f"recipe step {i}: input '{input_name}' must name a recipe "
                f"input (a string), got {type(ref).__name__}"
            )
        if ref not in available:
            raise ValueError(
                f"recipe step {i}: input '{input_name}' names recipe input "
                f"{ref!r}, which this run does not supply "
                f"(has: {sorted(available) or 'none'})"
            )
    missing = [n for n, spec_in in spec.inputs.items() if spec_in.required and n not in refs]
    if missing:
        raise ValueError(
            f"recipe step {i}: op '{name}' needs auxiliary input(s) "
            f"{sorted(missing)} — name them in the step's 'inputs' and bind "
            f"them when the recipe runs"
        )


def run_recipe(
    ds: DataStruct,
    steps: list[dict[str, Any]],
    progress: Callable[[int, int, OpResult], None] | None = None,
    inputs: Mapping[str, DataStruct | list[DataStruct]] | None = None,
) -> RecipeResult:
    """Run an ordered recipe over ``ds``. Image steps chain; value steps run
    against the current chained image. Raises on a bad op/params (the caller
    decides per-input try/continue for multi-input batches).

    ``inputs`` is the run's pool of auxiliary datasets, keyed by the symbolic
    names the steps reference. Already-resolved ``DataStruct``s: the caller
    owns the session store, the pure layer never looks an id up (ADR 0005 §8).
    """
    pool = dict(inputs or {})
    validate_recipe(steps, pool)
    results: list[OpResult] = []
    values: list[OpResult] = []
    current = ds
    for index, step in enumerate(steps):
        bound = {name: pool[ref] for name, ref in step_inputs(step).items()}
        result = run(step["op"], current, step.get("params"), inputs=bound or None)
        results.append(result)
        if result.produces_image and result.derived is not None:
            current = result.derived
        else:
            values.append(result)
        if progress is not None:
            progress(index + 1, len(steps), result)
    return RecipeResult(steps=results, final=current, values=values)
