"""Server-backed analysis recipes over multiple session images."""

from __future__ import annotations

import datetime as _dt
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


class BatchRunRequest(BaseModel):
    image_ids: list[str] = Field(min_length=1, max_length=200)
    steps: list[BatchStepRequest] = Field(min_length=1, max_length=30)


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
                "inputs": [
                    _input_schema(name, inp) for name, inp in spec.inputs.items()
                ],
                # A recipe step carries one subject, so an op needing extra
                # datasets is callable but not scriptable as a batch step
                # (`ops/batch.validate_recipe` rejects it) — say so in the
                # palette rather than letting a builder offer it and fail.
                "recipe_step": not spec.multi_input,
            }
            for spec in ops.list_ops()
        ],
    }


def validate_recipe_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Structural + per-op param validation, shared by ``/batch/run`` and
    the folder-watch route (``routes/watch.py``): raises HTTPException(422)
    on the first bad step so a queued job can never start with a recipe
    that would fail on every input."""
    try:
        validate_recipe(steps)
        for step in steps:
            spec = ops.get_spec(step["op"])
            spec.resolve_params(step.get("params"))
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from None
    return steps


def _validated_steps(req: BatchRunRequest) -> list[dict[str, Any]]:
    return validate_recipe_steps([step.model_dump() for step in req.steps])


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
) -> dict[str, Any]:
    """Register a recipe's final chained image as a derived image with
    lineage + the recipe in its metadata. Shared with the folder-watch
    route's single-file job (``routes/watch.py``)."""
    derived = DataStruct(
        data=np.asarray(final.data),
        kind=final.kind,
        axes=final.axes,
        metadata={
            **final.metadata,
            "source": f"batch({source_name})",
            "parser": "derived",
            "analysis": "batch_recipe",
            "recipe_version": 1,
            "recipe": steps,
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
) -> dict[str, Any]:
    total = len(image_ids) * len(steps)
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

            recipe = run_recipe(source, steps, progress=step_progress)
            has_image = any(step.produces_image for step in recipe.steps)
            derived = (
                register_final_image(image_id, source_name, recipe.final, steps)
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
        "outputs": outputs,
        "succeeded": sum(item["status"] == "done" for item in outputs),
        "failed": sum(item["status"] == "error" for item in outputs),
    }


@router.post("/batch/run")
def batch_run(req: BatchRunRequest) -> dict[str, str]:
    """Queue a recipe and retain independent success/failure per input."""
    steps = _validated_steps(req)
    _validate_images(req.image_ids)
    try:
        job_id = jobs.submit(
            lambda report: _run_batch(req.image_ids, steps, report)
        )
    except JobQueueFullError as exc:
        raise HTTPException(429, str(exc)) from None
    return {"job_id": job_id}
