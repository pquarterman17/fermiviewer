"""Server-backed analysis recipes over multiple session images."""

from __future__ import annotations

import datetime as _dt
from collections.abc import Collection
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import fermiviewer.ops as ops
from fermiviewer.datastruct import DataStruct
from fermiviewer.jobs import JobQueueFullError, ProgressFn, jobs
from fermiviewer.models import ImageMeta
from fermiviewer.ops.batch import run_recipe, validate_recipe
from fermiviewer.session import UnknownImageError, store

router = APIRouter(prefix="/api")


class BatchStepRequest(BaseModel):
    op: str
    params: dict[str, Any] = Field(default_factory=dict)
    # {op input name: recipe input name} for a multi-input op (ADR 0005 §8).
    # The value names an entry in the run's `inputs` pool, never an image id:
    # a saved recipe must stay runnable over other images and other sessions.
    inputs: dict[str, str] = Field(default_factory=dict)


class BatchRunRequest(BaseModel):
    image_ids: list[str] = Field(min_length=1, max_length=200)
    steps: list[BatchStepRequest] = Field(min_length=1, max_length=30)
    # the pool the steps' input names resolve against: recipe input name ->
    # one image id, or several for a variadic op input
    inputs: dict[str, str | list[str]] = Field(default_factory=dict)


def json_safe(value: Any) -> Any:
    """NaN/Inf-safe, numpy-scalar-safe JSON coercion — shared with
    routes/watch.py's single-file recipe job result.

    No op in this repo currently emits datetime64/timedelta64/complex/bytes
    as an OpResult.value, but this is the ONE choke point every op's value
    passes through before a job result is considered JSON-safe — silently
    passing an unhandled type through here (the old behavior, the `dict`/
    `list` branches would just recurse into it unchanged) doesn't fail
    here, it fails later at actual response-encoding time with a bare
    "Object of type X is not JSON serializable", far from this function.
    Handled explicitly instead of "clearly rejected": a op author adding a
    timestamp or complex-valued result later shouldn't have to rediscover
    this.
    """
    if isinstance(value, float):
        return value if np.isfinite(value) else None
    if isinstance(value, complex):  # incl. np.complexfloating (subclasses complex)
        return {"real": json_safe(value.real), "imag": json_safe(value.imag)}
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, (np.datetime64, np.timedelta64)):
        return str(value)
    if isinstance(value, _dt.timedelta):
        return value.total_seconds()
    if isinstance(value, _dt.date):  # covers datetime.datetime too
        return value.isoformat()
    if isinstance(value, np.generic):
        return json_safe(value.item())
    if isinstance(value, np.ndarray):
        return json_safe(value.tolist())
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def _param_schema(name: str, param: ops.OpParam) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "name": name,
        "type": param.describe_type(),
        "default": param.default,
        "required": param.required,
        "minimum": param.minimum,
        "maximum": param.maximum,
        "exclusive_minimum": param.exclusive_minimum,
        "exclusive_maximum": param.exclusive_maximum,
        "choices": list(param.choices) if param.choices is not None else None,
        "doc": param.doc,
    }
    # A list-shaped param (ADR 0005 §9) carries its row/record structure so a
    # palette can build the right editor instead of guessing from "list".
    if param.row is not None:
        schema["shape"] = {
            "kind": "rows",
            "width": param.row.width,
            "item_type": param.row.item_type.__name__,
            "columns": list(param.row.columns),
            "min_rows": param.row.min_rows,
            "max_rows": param.row.max_rows,
            "allow_none_rows": param.row.allow_none_rows,
        }
    elif param.record is not None:
        schema["shape"] = {
            "kind": "records",
            "min_rows": param.record.min_rows,
            "max_rows": param.record.max_rows,
            "fields": [
                _param_schema(fname, fparam)
                for fname, fparam in param.record.fields.items()
            ],
        }
    return schema


def _input_schema(name: str, spec: ops.OpInput) -> dict[str, Any]:
    """One auxiliary dataset an op needs beyond its subject (ADR 0005 §8) —
    the palette needs this to know an op wants a second image picker."""
    return {
        "name": name,
        "required": spec.required,
        "variadic": spec.variadic,
        "min_count": spec.min_count if spec.variadic else None,
        "max_count": spec.max_count if spec.variadic else None,
        "kinds": [k.value for k in spec.kinds] if spec.kinds is not None else None,
        "doc": spec.doc,
    }


@router.get("/batch/operations")
def batch_operations() -> dict[str, Any]:
    """The authoritative recipe palette and parameter schemas."""
    return {
        "version": 1,
        "operations": [
            {
                "name": spec.name,
                "category": spec.category,
                "summary": spec.summary,
                "produces": "analysis"
                if ops.produces_value_result(spec)
                else "image",
                "params": [
                    _param_schema(name, param)
                    for name, param in spec.params.items()
                ],
                # An op needing extra datasets IS scriptable now (ADR 0005
                # §8): a builder renders one picker per entry and binds it in
                # the run's `inputs` pool. The short-lived `recipe_step` flag
                # that said "not scriptable" is gone with the reason for it.
                "inputs": [
                    _input_schema(name, inp) for name, inp in spec.inputs.items()
                ],
            }
            for spec in ops.list_ops()
        ],
    }


def validate_recipe_steps(
    steps: list[dict[str, Any]], input_names: Collection[str] = ()
) -> list[dict[str, Any]]:
    """Structural + per-op param validation, shared by ``/batch/run`` and
    the folder-watch route (``routes/watch.py``): raises HTTPException(422)
    on the first bad step so a queued job can never start with a recipe
    that would fail on every input. ``input_names`` are the recipe input
    names the run will bind, so an unresolvable reference is a 422 too."""
    try:
        validate_recipe(steps, input_names)
        for step in steps:
            spec = ops.get_spec(step["op"])
            spec.resolve_params(step.get("params"))
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from None
    return steps


def resolve_recipe_inputs(
    inputs: dict[str, str | list[str]],
) -> dict[str, Any]:
    """Recipe input pool: image id(s) -> ``DataStruct``(s).

    This is the id-resolution step ADR 0005 §8 puts on the CALLER — the pure
    recipe runner receives datasets, never ids, so a recipe stays portable
    and ``ops/`` never reads the session store."""
    missing: list[str] = []
    pool: dict[str, Any] = {}
    for name, ref in inputs.items():
        ids = ref if isinstance(ref, list) else [ref]
        resolved = []
        for image_id in ids:
            try:
                resolved.append(store.get(image_id))
            except UnknownImageError:
                missing.append(image_id)
        pool[name] = resolved if isinstance(ref, list) else (resolved[0] if resolved else None)
    if missing:
        raise HTTPException(404, f"unknown image id(s): {missing}")
    return pool


def _validated_steps(req: BatchRunRequest) -> list[dict[str, Any]]:
    return validate_recipe_steps(
        [step.model_dump() for step in req.steps], req.inputs
    )


def _validate_images(image_ids: list[str]) -> None:
    missing = []
    for image_id in image_ids:
        try:
            store.get(image_id)
        except UnknownImageError:
            missing.append(image_id)
    if missing:
        raise HTTPException(404, f"unknown image id(s): {missing}")


def register_final_image(
    image_id: str,
    source_name: str,
    final: DataStruct,
    steps: list[dict[str, Any]],
    recipe_inputs: dict[str, str | list[str]] | None = None,
) -> dict[str, Any]:
    """Register a recipe's final chained image as a derived image with
    lineage + the recipe in its metadata. Shared with the folder-watch
    route's single-file job (``routes/watch.py``).

    ``recipe_inputs`` is the id binding the steps' symbolic input names
    resolved to for THIS run. The steps alone no longer describe the
    computation once a step can name an auxiliary dataset, so the binding is
    recorded beside them (version 2)."""
    derived = DataStruct(
        data=np.asarray(final.data),
        kind=final.kind,
        axes=final.axes,
        metadata={
            **final.metadata,
            "source": f"batch({source_name})",
            "parser": "derived",
            "analysis": "batch_recipe",
            # 2: steps may carry an "inputs" map of symbolic names, resolved
            # by the sibling "recipe_inputs" binding (ADR 0005 §8)
            "recipe_version": 2,
            "recipe": steps,
            "recipe_inputs": dict(recipe_inputs or {}),
        },
    )
    name = f"batch({source_name})"
    derived_id = store.add_derived(derived, name, image_id)
    return ImageMeta.from_datastruct(
        derived_id, name, derived,
    ).model_dump()


def _run_batch(
    image_ids: list[str],
    steps: list[dict[str, Any]],
    report: ProgressFn,
    recipe_inputs: dict[str, str | list[str]] | None = None,
) -> dict[str, Any]:
    total = len(image_ids) * len(steps)
    bindings = dict(recipe_inputs or {})
    # resolved ONCE for the whole batch: the pool is the same datasets for
    # every subject, and re-reading the store per input would let a
    # mid-batch deletion change the computation half way through
    pool = resolve_recipe_inputs(bindings)
    outputs: list[dict[str, Any]] = []
    for input_index, image_id in enumerate(image_ids):
        source_name = store.name(image_id)
        try:
            source = store.get(image_id)

            def step_progress(
                step_index: int,
                _step_total: int,
                result: ops.OpResult,
                input_offset: int = input_index,
                input_name: str = source_name,
            ) -> None:
                complete = input_offset * len(steps) + step_index
                report(
                    complete / total,
                    f"{input_name}: {result.label} "
                    f"({step_index}/{len(steps)})",
                )

            recipe = run_recipe(source, steps, progress=step_progress, inputs=pool)
            has_image = any(step.produces_image for step in recipe.steps)
            derived = (
                register_final_image(
                    image_id, source_name, recipe.final, steps, bindings
                )
                if has_image
                else None
            )
            outputs.append({
                "image_id": image_id,
                "name": source_name,
                "status": "done",
                "derived": derived,
                "values": [
                    {
                        "op": result.op,
                        "label": result.label,
                        "params": result.params,
                        "value": json_safe(result.value),
                    }
                    for result in recipe.values
                ],
            })
        except Exception as exc:  # noqa: BLE001 - per-input failure is a result
            outputs.append({
                "image_id": image_id,
                "name": source_name,
                "status": "error",
                "error": str(exc),
                "derived": None,
                "values": [],
            })
            report(
                ((input_index + 1) * len(steps)) / total,
                f"{source_name}: failed",
            )
    return {
        "version": 1,
        "steps": steps,
        "inputs": bindings,
        "outputs": outputs,
        "succeeded": sum(item["status"] == "done" for item in outputs),
        "failed": sum(item["status"] == "error" for item in outputs),
    }


@router.post("/batch/run")
def batch_run(req: BatchRunRequest) -> dict[str, str]:
    """Queue a recipe and retain independent success/failure per input."""
    steps = _validated_steps(req)
    _validate_images(req.image_ids)
    # resolve the pool here too, so an unknown auxiliary id is a 404 BEFORE
    # the job is queued — the same "never queue a recipe that must fail"
    # rule the param validation above follows
    resolve_recipe_inputs(req.inputs)
    try:
        job_id = jobs.submit(
            lambda report: _run_batch(req.image_ids, steps, report, req.inputs)
        )
    except JobQueueFullError as exc:
        raise HTTPException(429, str(exc)) from None
    return {"job_id": job_id}
