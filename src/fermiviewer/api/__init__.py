"""``fermiviewer.api`` — the documented public Python surface (Scripting #2).

The stable, semver-able front door for scripting and notebooks. It shares the
exact pure engine the FastAPI server uses (``io`` + ``calc`` + ``ops``) — one
engine, two front doors (HTTP and Python) — but never imports ``routes``, so it
runs headless with no server.

    import fermiviewer.api as fv
    img = fv.open("scan.dm4")
    blurred = img.gaussian(sigma=2).image      # derived Image
    stats = img.image_stats().value            # {'mean': ..., 'std': ...}

Every registered operation (``fv.ops()`` lists them) is callable as a method:
``img.<op>(**params) -> Result``. A Result carries ``.value`` (scalar/table) or
``.image`` (a derived Image), plus ``.params`` for reproducibility.

Stability: the names in ``__all__`` and the documented method surface are the
contract. ``calc/`` internals are private and may churn; this façade is not.
"""

from __future__ import annotations

import io as _io
import itertools
from pathlib import Path
from typing import Any

import numpy as np

from fermiviewer import ops as _ops
from fermiviewer.calc.raster import raster_of
from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.io.registry import load_auto
from fermiviewer.ops.provenance import ProvenanceLog, ProvenanceStep

__all__ = ["Image", "Result", "Session", "open", "ops"]

_ids = itertools.count(1)


def ops() -> list[dict[str, Any]]:
    """The registered operation catalogue: name, category, summary, params."""
    return [
        {
            "name": s.name,
            "category": s.category,
            "summary": s.summary,
            "params": {
                p: {"type": spec.ptype.__name__, "default": spec.default}
                for p, spec in s.params.items()
            },
        }
        for s in _ops.list_ops()
    ]


class Result:
    """The outcome of running an operation: a derived ``Image`` (``.image``)
    or a plain value (``.value``), plus the resolved ``.params``."""

    def __init__(self, op_result: _ops.OpResult, session: Session) -> None:
        self._r = op_result
        self._image: Image | None = (
            session._adopt(op_result.derived, op_result.label)
            if op_result.derived is not None
            else None
        )

    @property
    def value(self) -> Any:
        return self._r.value

    @property
    def params(self) -> dict[str, Any]:
        return dict(self._r.params)

    @property
    def op(self) -> str:
        return self._r.op

    @property
    def image(self) -> Image | None:
        """The derived image, or None for value-producing ops."""
        return self._image

    def to_image(self) -> Image | None:
        return self._image

    def __repr__(self) -> str:
        if self._image is not None:
            return f"<Result op={self._r.op!r} → {self._image!r}>"
        return f"<Result op={self._r.op!r} value={self._r.value!r}>"

    def _repr_html_(self) -> str:  # notebook display
        if self._image is not None:
            return self._image._repr_html_()
        return f"<b>{self._r.op}</b><pre>{self._r.value}</pre>"

    def to_csv(self) -> bytes:
        """A dict-shaped ``.value`` (image_stats/noise/roughness/...) as a
        one-row CSV — delegates to calc/table_export.py's flatten+serialize
        helpers (Scripting #4)."""
        from fermiviewer.calc.table_export import flatten_value_dict, table_to_csv_bytes

        if not isinstance(self._r.value, dict):
            raise TypeError("to_csv() requires a dict-shaped .value result")
        columns, rows = flatten_value_dict(self._r.value)
        return table_to_csv_bytes(columns, rows)

    def to_json(self) -> bytes:
        """A dict-shaped ``.value`` as one-row-table JSON (see ``to_csv``)."""
        from fermiviewer.calc.table_export import flatten_value_dict, table_to_json_bytes

        if not isinstance(self._r.value, dict):
            raise TypeError("to_json() requires a dict-shaped .value result")
        columns, rows = flatten_value_dict(self._r.value)
        return table_to_json_bytes(columns, rows)


def _flatten(value: Any) -> list[Image]:
    """One Image, a list of them, or nothing — as a flat list."""
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _split_inputs(
    spec: Any, supplied: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Peel the op's declared auxiliary inputs out of the keyword arguments,
    leaving the rest as params. Keyword arguments are how a notebook reads
    (``a.image_math(other=b)``), so inputs and params share one namespace
    here and the spec decides which is which."""
    inputs = {name: supplied.pop(name) for name in spec.inputs if name in supplied}
    return inputs, supplied


def _as_structs(inputs: dict[str, Any]) -> dict[str, Any]:
    """``Image`` -> ``DataStruct`` (the pure layer speaks structs, not
    session objects); a plain ``DataStruct`` passes through, so the façade
    accepts either."""
    out: dict[str, Any] = {}
    for name, value in inputs.items():
        if isinstance(value, (list, tuple)):
            out[name] = [v.datastruct if isinstance(v, Image) else v for v in value]
        else:
            out[name] = value.datastruct if isinstance(value, Image) else value
    return out


class Image:
    """A loaded dataset: a thin, notebook-friendly wrapper over a
    ``DataStruct``. Run any registered op as a method (``img.gaussian(...)``)
    or via ``img.run(name, **params)``."""

    def __init__(
        self, ds: DataStruct, name: str, session: Session, image_id: str
    ) -> None:
        self._ds = ds
        self._name = name
        self._session = session
        self.id = image_id

    # ── identity / data access ────────────────────────────────────────
    @property
    def name(self) -> str:
        return self._name

    @property
    def kind(self) -> str:
        return str(self._ds.kind)

    @property
    def shape(self) -> tuple[int, ...]:
        return tuple(self._ds.data.shape)

    @property
    def pixel_size(self) -> float:
        if self._ds.kind is DataKind.SPECTRUM:
            return float("nan")
        return self._ds.pixel_size

    @property
    def pixel_unit(self) -> str:
        if self._ds.kind is DataKind.SPECTRUM:
            return ""
        return self._ds.pixel_unit

    @property
    def metadata(self) -> dict[str, Any]:
        return dict(self._ds.metadata)

    @property
    def datastruct(self) -> DataStruct:
        """The underlying DataStruct (the bridge to the pure calc/ layer)."""
        return self._ds

    def to_numpy(self) -> np.ndarray:
        """A writeable copy of the pixel/spectrum array."""
        return np.array(self._ds.data)

    @property
    def energy_axis(self) -> np.ndarray:
        """Calibrated energy axis (spectral kinds only)."""
        return self._ds.energy_axis

    # ── operations ────────────────────────────────────────────────────
    def run(self, op: str, /, **params: Any) -> Result:
        """Run a registered operation by name, returning a ``Result``. The
        session records a provenance step (params + lineage) for it.

        The operation name is positional-ONLY so that it cannot collide with
        a param of the same name: ``image_math`` mirrors its route's request
        model, which calls the arithmetic selector ``op``, and
        ``a.image_math(op="subtract")`` must reach the param.

        An op that declares auxiliary inputs (``image_math``'s second image,
        ``mip``'s remaining frames) takes them as ``Image`` keyword
        arguments — ``a.image_math(other=b, op="subtract")``,
        ``a.mip(others=[b, c])`` — and every contributing image is recorded
        in the step's lineage, not just the subject.
        """
        spec = _ops.get_spec(op)
        inputs, params = _split_inputs(spec, params)
        op_result = _ops.run(op, self._ds, params, inputs=_as_structs(inputs))
        result = Result(op_result, self._session)
        out_id = result.image.id if result.image is not None else None
        extra = [img for name in spec.inputs for img in _flatten(inputs.get(name))]
        self._session._record(
            op=op_result.op,
            params=op_result.params,
            label=op_result.label,
            inputs=(self.id, *(i.id for i in extra)),
            input_names=(self._name, *(i.name for i in extra)),
            output=out_id,
            value=op_result.value if out_id is None else None,
        )
        return result

    def pipeline(self, steps: list[dict[str, Any]]) -> list[Result]:
        """Run an ordered recipe (``[{"op": name, "params": {...}}, ...]``),
        chaining derived images. Each step is recorded in provenance; returns
        a Result per step. The final image is ``[r.image for r ...][-1]``."""
        results: list[Result] = []
        current: Image = self
        for step in steps:
            r = current.run(step["op"], **(step.get("params") or {}))
            results.append(r)
            if r.image is not None:
                current = r.image
        return results

    def methods(self) -> str:
        """A reproducible methods paragraph for this image's pipeline."""
        return self._session.provenance.to_markdown(self.id)

    def provenance_json(self) -> str:
        """JSON of this image's full ancestry chain."""
        return self._session.provenance.to_json(self.id)

    def __getattr__(self, name: str) -> Any:
        # expose every registered op as a method: img.<op>(**params)
        try:
            _ops.get_spec(name)
        except _ops.UnknownOpError:
            raise AttributeError(name) from None

        def _call(**params: Any) -> Result:
            return self.run(name, **params)

        _call.__name__ = name
        return _call

    def __dir__(self) -> list[str]:
        return sorted(set(super().__dir__()) | {s.name for s in _ops.list_ops()})

    # ── display ───────────────────────────────────────────────────────
    def __repr__(self) -> str:
        cal = (
            f", {self.pixel_size:g} {self.pixel_unit}/px"
            if self._ds.kind is not DataKind.SPECTRUM and self.pixel_unit
            else ""
        )
        return f"<Image {self._name!r} {self.kind} {self.shape}{cal}>"

    def _repr_html_(self) -> str:
        rows = "".join(
            f"<tr><td><b>{k}</b></td><td>{v}</td></tr>"
            for k, v in (
                ("name", self._name),
                ("kind", self.kind),
                ("shape", self.shape),
                ("pixel size", f"{self.pixel_size:g} {self.pixel_unit}/px"),
            )
        )
        return f"<table>{rows}</table>"

    def _repr_png_(self) -> bytes | None:  # notebook image preview
        if self._ds.kind is DataKind.SPECTRUM:
            return None
        try:
            from PIL import Image as _PILImage

            from fermiviewer.calc.export import render_rgb
        except ImportError:  # pragma: no cover
            return None
        raster = raster_of(self._ds)
        rgb = render_rgb(raster, None, None, 1.0, "gray", 1)
        buf = _io.BytesIO()
        _PILImage.fromarray(rgb, mode="RGB").save(buf, format="PNG")
        return buf.getvalue()


class Session:
    """An in-process workspace mirroring the server's store: it holds opened +
    derived images and the ``derived_from`` lineage between them, so a scripted
    pipeline accumulates exactly like the GUI session."""

    def __init__(self) -> None:
        self.images: dict[str, Image] = {}
        self.provenance = ProvenanceLog()

    def open(self, path: str | Path) -> Image:
        """Load a file (any registered format) into this session."""
        ds = load_auto(path)
        return self._adopt(ds, Path(path).name)

    def _adopt(self, ds: DataStruct, name: str) -> Image:
        image_id = f"img{next(_ids)}"
        img = Image(ds, name, self, image_id)
        self.images[image_id] = img
        return img

    def _record(self, **kw: Any) -> None:
        self.provenance.record(ProvenanceStep(**kw))


_default = Session()


def open(path: str | Path) -> Image:  # noqa: A001 — public API verb, by design
    """Load a file into the default session and return an ``Image``."""
    return _default.open(path)
