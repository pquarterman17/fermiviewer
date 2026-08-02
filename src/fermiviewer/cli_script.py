"""Headless script runner — ``fv --script recipe.json inputs...`` (Scripting #10).

Runs a saved batch recipe — the SAME ``.fvbatch.json`` preset BatchDialog's
export button writes, or a bare ``{"steps": [...]}`` recipe — over one or
more inputs with no server and no browser: a CLI pipeline step for
cluster/CI use. Drives the public façade (``fermiviewer.api``), the same
engine the GUI's batch endpoints and notebooks use, rather than re-plumbing
``ops``/``io`` — a recipe that runs in the app runs identically here.

For each input, writes into the output directory:

- the recipe's FINAL chained image (if any op produced one) as a
  data-preserving float32 TIFF — never window/gamma-quantized, this is a
  data product, not a figure: ``<stem>.<recipe-or-op>.<tif>`` (the recipe's
  saved name when the file carries one, else the name of the op that
  produced it, else "recipe")
- each value-producing step's result as CSV *and* JSON (``calc/table_export``):
  ``<stem>.<op>.csv`` / ``<stem>.<op>.json`` (a repeated op name within one
  recipe is disambiguated ``<op>_2``, ``<op>_3``, ...)
- a provenance JSON, ``<stem>.provenance.json`` — the complete, unfiltered
  step log for this input (not just image lineage, so value-only steps are
  never silently dropped) — and, only when at least one image was
  produced (the methods paragraph walks the image lineage), a
  methods-paragraph Markdown, ``<stem>.methods.md``

Per-input failures are isolated: a bad file is logged and skipped, the rest
of the run continues, and the process exit code is 1 if ANY input failed
(0 if every input succeeded). A malformed recipe, an unknown op/param, or
"nothing matched" is a hard, upfront failure (exit 2) — no input is touched.

App-layer module, like ``server.py``/``watch.py``: imports ``api``/``ops``/
``io``/``calc`` and stdlib only, never ``routes`` — kept out of the
``io``/``calc``/``ops`` PURE_LAYERS import graph checked by
``tests/test_repo_integrity.py``, but held to the same bar.
"""

from __future__ import annotations

import glob
import json
import re
import sys
from pathlib import Path
from typing import Any, TextIO

import numpy as np

from fermiviewer.api import Session
from fermiviewer.calc.table_export import (
    flatten_value_dict,
    table_to_csv_bytes,
    table_to_json_bytes,
)
from fermiviewer.ops import UnknownOpError, get_spec
from fermiviewer.ops.batch import validate_recipe
from fermiviewer.watch import default_is_openable

__all__ = ["RecipeError", "load_recipe", "run_script"]


class RecipeError(ValueError):
    """A malformed or invalid recipe — always exit 2, before any input is
    touched."""


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "recipe"


_GLOB_MAGIC = re.compile(r"[*?\[]")


def _looks_like_glob(raw: str) -> bool:
    return bool(_GLOB_MAGIC.search(raw))


def _named(value: dict[str, Any]) -> str | None:
    name = value.get("name")
    return name.strip() if isinstance(name, str) and name.strip() else None


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        # UnicodeDecodeError (not an OSError subclass) is just as much a
        # malformed-recipe-file condition as a bad path or invalid JSON —
        # without this, a non-UTF-8 recipe file would crash with a raw
        # traceback instead of the documented "exit 2, nothing touched"
        # contract every other load_recipe() failure honors.
        raise RecipeError(f"cannot read recipe file '{path}': {exc}") from None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RecipeError(f"recipe file '{path}' is not valid JSON: {exc}") from None
    if not isinstance(data, dict):
        raise RecipeError(f"recipe file '{path}' must contain a JSON object")
    return data


def _extract_steps_and_name(
    data: dict[str, Any], path: Path
) -> tuple[Any, str | None]:
    """Unwrap either shape ``load_recipe`` accepts, returning the raw
    (not yet validated) steps value and an optional recipe name."""
    if "preset" in data:
        preset = data["preset"]
        if not isinstance(preset, dict) or "steps" not in preset:
            raise RecipeError(
                f"recipe file '{path}': 'preset' must be an object with a "
                "'steps' array"
            )
        return preset["steps"], _named(preset)
    if "steps" in data:
        return data["steps"], _named(data)
    raise RecipeError(
        f"recipe file '{path}' has no 'steps' array — expected either a "
        "bare {'steps': [...]} recipe or a saved .fvbatch.json preset "
        "export ({'format': 'fermiviewer-batch-preset', ..., 'preset': "
        "{'steps': [...]}})"
    )


def _normalize_steps(raw_steps: Any, path: Path) -> list[dict[str, Any]]:
    if not isinstance(raw_steps, list) or not raw_steps:
        raise RecipeError(f"recipe file '{path}': 'steps' must be a non-empty array")
    steps: list[dict[str, Any]] = []
    for i, step in enumerate(raw_steps):
        if not isinstance(step, dict) or not isinstance(step.get("op"), str):
            raise RecipeError(
                f"recipe file '{path}': step {i} must be an object with a "
                "string 'op'"
            )
        params = step.get("params") or {}
        if not isinstance(params, dict):
            raise RecipeError(
                f"recipe file '{path}': step {i}'s 'params' must be an object"
            )
        steps.append({"op": step["op"], "params": dict(params)})
    return steps


def load_recipe(path: Path) -> tuple[list[dict[str, Any]], str | None]:
    """Load + structurally validate a recipe file.

    Accepts a full ``.fvbatch.json`` preset export — exactly what
    BatchDialog's export button writes:
    ``{"format": "fermiviewer-batch-preset", "version": 1, "preset":
    {"steps": [...], "name": ..., ...}}`` — OR a bare
    ``{"steps": [{"op": ..., "params": {...}}, ...]}`` recipe with no
    wrapper/version at all (an optional top-level ``"name"`` is honored the
    same way). Returns ``(steps, name)``; ``name`` is the preset's/recipe's
    name when present, else None.

    Raises :class:`RecipeError` on anything structurally wrong. Op/param
    validity against the ops registry is checked separately — see
    ``_validate_ops`` — so a bad recipe always fails before any input file
    is touched, regardless of which check catches it first.
    """
    data = _read_json_object(path)
    raw_steps, name = _extract_steps_and_name(data, path)
    steps = _normalize_steps(raw_steps, path)
    return steps, name


def _validate_ops(steps: list[dict[str, Any]], recipe_path: Path) -> None:
    """Every op + its params must resolve against the ops registry BEFORE any
    input is touched — an unknown op or a bad param is always a recipe
    error (exit 2), never a per-input failure."""
    try:
        validate_recipe(steps)
        for step in steps:
            spec = get_spec(step["op"])
            spec.resolve_params(step.get("params"))
    except (ValueError, UnknownOpError) as exc:
        raise RecipeError(f"recipe file '{recipe_path}': {exc}") from None


def _expand_inputs(inputs: list[str]) -> list[Path]:
    """Files, top-level directory scans, and glob patterns -> a
    de-duplicated, order-preserving list of paths.

    Directories are scanned non-recursively (documented, not a bug — a
    pipeline step over a corpus tree runs once per top-level directory) and
    filtered to extensions the io registry's suffix map recognizes;
    content-sniffed formats (e.g. Nanoscope's numeric extensions) are not
    detected by suffix alone, mirroring ``watch.default_is_openable``'s
    documented limit — pass such files directly rather than via a
    directory. A literal path (no ``* ? [`` in it) that doesn't exist is
    still attempted, so a typo'd filename fails loudly as that one input's
    per-file error rather than silently vanishing; a glob PATTERN that
    matches nothing contributes no paths at all, so an all-patterns run can
    still trip the "nothing matched" upfront failure below.
    """
    paths: list[Path] = []
    for raw in inputs:
        matched = sorted(glob.glob(raw))
        if matched:
            candidates = [Path(m) for m in matched]
        elif _looks_like_glob(raw):
            candidates = []
        else:
            candidates = [Path(raw)]
        for candidate in candidates:
            if candidate.is_dir():
                for child in sorted(candidate.iterdir()):
                    if child.is_file() and default_is_openable(child):
                        paths.append(child)
            else:
                paths.append(candidate)
    seen: set[Path] = set()
    ordered: list[Path] = []
    for p in paths:
        key = p.resolve()
        if key not in seen:
            seen.add(key)
            ordered.append(p)
    return ordered


def _dedupe_stem(used: dict[str, int], stem: str) -> str:
    """``op`` / ``op_2`` / ``op_3``... when the same op name recurs in one
    recipe (e.g. two ``noise`` steps with different params)."""
    used[stem] = used.get(stem, 0) + 1
    n = used[stem]
    return stem if n == 1 else f"{stem}_{n}"


def _process_one(
    path: Path,
    steps: list[dict[str, Any]],
    recipe_name_slug: str | None,
    out_dir: Path,
) -> list[str]:
    """Run the recipe over one input and write its outputs. Returns the
    names of the files written (for the per-input summary line); raises on
    failure so the caller can isolate it per input."""
    import tifffile

    session = Session()  # fresh session per input — no cross-input provenance
    img = session.open(path)
    results = img.pipeline(steps)

    stem = path.stem
    written: list[str] = []

    last_image = None
    last_op: str | None = None
    value_counts: dict[str, int] = {}
    for result in results:
        if result.image is not None:
            last_image = result.image
            last_op = result.op
            continue
        op_stem = _dedupe_stem(value_counts, result.op)
        value = result.value
        columns, rows = (
            flatten_value_dict(value)
            if isinstance(value, dict)
            else (["value"], [[value]])
        )
        csv_path = out_dir / f"{stem}.{op_stem}.csv"
        csv_path.write_bytes(table_to_csv_bytes(columns, rows))
        written.append(csv_path.name)
        json_path = out_dir / f"{stem}.{op_stem}.json"
        json_path.write_bytes(table_to_json_bytes(columns, rows))
        written.append(json_path.name)

    if last_image is not None:
        name_component = recipe_name_slug or _slugify(last_op or "recipe")
        tif_path = out_dir / f"{stem}.{name_component}.tif"
        data = np.atleast_2d(np.asarray(last_image.to_numpy(), dtype=np.float32))
        tifffile.imwrite(tif_path, data)
        written.append(tif_path.name)

    # The unfiltered session log, not last_image.provenance_json()'s image-
    # lineage ancestry: a session is fresh per input (nothing to contaminate
    # it), so the full log IS this input's complete step record — including
    # value-producing steps that ran after the last image-producing one
    # (e.g. an image_stats() after a gaussian()), which an image-lineage walk
    # would silently omit since they never produced an image of their own.
    provenance_path = out_dir / f"{stem}.provenance.json"
    provenance_path.write_text(session.provenance.to_json(), encoding="utf-8")
    written.append(provenance_path.name)

    if last_image is not None:
        methods_path = out_dir / f"{stem}.methods.md"
        methods_path.write_text(last_image.methods() + "\n", encoding="utf-8")
        written.append(methods_path.name)

    return written


def run_script(
    recipe_path: str | Path,
    inputs: list[str],
    out_dir: str | Path,
    *,
    stdout: TextIO = sys.stdout,
) -> int:
    """Run ``recipe_path`` over every file matched by ``inputs``, writing
    outputs to ``out_dir``. Prints a one-line summary per input plus a
    final totals line.

    Returns the process exit code: ``2`` for a malformed/invalid recipe or
    when no input matched anything (nothing is touched in either case),
    ``1`` if any input failed, ``0`` if every input succeeded.
    """
    recipe_path = Path(recipe_path)
    try:
        steps, name = load_recipe(recipe_path)
        _validate_ops(steps, recipe_path)
    except RecipeError as exc:
        print(f"error: {exc}", file=stdout)
        return 2

    paths = _expand_inputs(inputs)
    if not paths:
        print(f"error: no input files matched {inputs!r}", file=stdout)
        return 2

    out_path = Path(out_dir)
    try:
        out_path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"error: cannot create output directory '{out_path}': {exc}", file=stdout)
        return 2

    recipe_name_slug = _slugify(name) if name else None
    failures = 0
    for path in paths:
        try:
            written = _process_one(path, steps, recipe_name_slug, out_path)
        except Exception as exc:  # noqa: BLE001 — one bad input must not stop the run
            failures += 1
            print(f"FAIL  {path}: {exc}", file=stdout)
            continue
        print(f"OK    {path} -> {', '.join(written)}", file=stdout)

    total = len(paths)
    print(f"{total - failures}/{total} succeeded, {failures} failed", file=stdout)
    return 1 if failures else 0
