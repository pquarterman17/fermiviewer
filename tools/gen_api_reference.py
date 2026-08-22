#!/usr/bin/env python3
"""Generate ``docs/api-reference.md`` from ``fermiviewer.api``'s public
surface and the ops registry (Scripting #11).

Regenerate after touching ``fermiviewer.api`` or any op catalogue:

    uv run python tools/gen_api_reference.py

``tests/test_api_reference.py`` regenerates this in memory on every test run
and fails if the committed file doesn't match byte-for-byte — the
generated file must never be hand-edited; change the source it reads
from and rerun this script instead.

stdlib ``inspect`` only, no doc-generation dependency (sphinx/pdoc/
mkdocs all sit outside this project's dependency policy for a single
generated page). Output is deterministic: ``OpSpec``/``OpParam`` dicts
preserve their Python literal insertion order and ``ops.list_ops()``
sorts by ``(category, name)``, so two runs against the same source
produce byte-identical markdown — which is what makes the drift-guard
test meaningful.

App-layer tool (like ``tools/make_synthetic_si.py``): imports
``fermiviewer.api``/``fermiviewer.ops`` and stdlib only.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import fermiviewer.api as fvapi  # noqa: E402
import fermiviewer.ops as fvops  # noqa: E402
from fermiviewer.ops.base import OpParam, OpSpec, produces_value_result  # noqa: E402

OUT_PATH = ROOT / "docs" / "api-reference.md"

# Instance attributes set in __init__ that aren't class-level properties, so
# the introspection below can't discover them from the class object alone.
# Hand-maintained (small, stable) rather than parsed out of __init__'s source.
_EXTRA_ATTRS: dict[str, list[tuple[str, str, str]]] = {
    "Image": [
        ("id", "str", "Session-scoped identifier; keys provenance and lineage."),
    ],
    "Session": [
        ("images", "dict[str, Image]", "Every opened/derived image, keyed by id."),
        (
            "provenance",
            "ProvenanceLog",
            "The append-only step log methods()/provenance_json() read from.",
        ),
    ],
}


def _doc(obj: object) -> str:
    return inspect.getdoc(obj) or ""


def _sig(fn: Any) -> str:
    """A signature string with clean (unquoted) annotations.

    ``from __future__ import annotations`` is active in ``fermiviewer.api``,
    so every annotation ``inspect.signature`` sees is already a plain string
    (e.g. ``"list[dict[str, Any]]"``) — but ``Signature.__str__`` doesn't
    know that and ``repr()``s it, producing ``def run(op: 'str')``. Render
    it by hand instead so the doc reads like real Python source.
    """
    sig = inspect.signature(fn)
    parts = []
    for name, p in sig.parameters.items():
        if name == "self":
            continue
        prefix = "*" if p.kind is p.VAR_POSITIONAL else "**" if p.kind is p.VAR_KEYWORD else ""
        piece = prefix + name
        if p.annotation is not inspect.Parameter.empty:
            piece += f": {p.annotation}"
        if p.default is not inspect.Parameter.empty:
            piece += f" = {p.default!r}"
        parts.append(piece)
    ret = ""
    if sig.return_annotation is not inspect.Signature.empty:
        ret = f" -> {sig.return_annotation}"
    return f"({', '.join(parts)}){ret}"


def _public_properties(cls: type) -> list[tuple[str, property]]:
    return [
        (name, val)
        for name, val in vars(cls).items()
        if isinstance(val, property) and not name.startswith("_")
    ]


def _public_methods(cls: type) -> list[tuple[str, Any]]:
    return [
        (name, val)
        for name, val in vars(cls).items()
        if inspect.isfunction(val) and not name.startswith("_")
    ]


def _render_class(name: str, cls: type) -> str:
    lines = [f"## `{name}`", "", _doc(cls), ""]

    extras = _EXTRA_ATTRS.get(name, [])
    if extras:
        lines.append("**Attributes:**")
        lines.extend(f"- `{n}` (`{t}`) — {d}" for n, t, d in extras)
        lines.append("")

    for pname, prop in _public_properties(cls):
        assert prop.fget is not None
        lines.append(f"### `{name}.{pname}` (property)")
        lines.append("")
        lines.append(f"```python\n{pname}: {_return_annotation(prop.fget)}\n```")
        lines.append("")
        lines.append(_doc(prop.fget) or "*(no docstring)*")
        lines.append("")

    for mname, fn in _public_methods(cls):
        lines.append(f"### `{name}.{mname}()`")
        lines.append("")
        lines.append(f"```python\ndef {mname}{_sig(fn)}\n```")
        lines.append("")
        lines.append(_doc(fn) or "*(no docstring)*")
        lines.append("")

    return "\n".join(lines)


def _return_annotation(fn: Any) -> str:
    sig = inspect.signature(fn)
    ret = sig.return_annotation
    return "Any" if ret is inspect.Signature.empty else str(ret)


def _render_function(name: str, fn: Any) -> str:
    return "\n".join(
        [
            f"## `{name}()`",
            "",
            f"```python\ndef {name}{_sig(fn)}\n```",
            "",
            _doc(fn) or "*(no docstring)*",
            "",
        ]
    )


def _render_surface() -> str:
    sections = []
    for name in fvapi.__all__:
        obj = getattr(fvapi, name)
        sections.append(
            _render_class(name, obj) if inspect.isclass(obj) else _render_function(name, obj)
        )
    return "\n".join(sections)


# ── ops table ────────────────────────────────────────────────────────

def _cell(text: str) -> str:
    """Escape literal ``|`` so a param doc containing one (e.g. eels_quantify's
    "'K'|'L'") can't be mistaken for an extra table column."""
    return text.replace("|", "\\|")


def _param_cell(value: Any) -> str:
    return "" if value is None else _cell(str(value))


def _choices_cell(param: OpParam) -> str:
    return _cell(", ".join(repr(c) for c in param.choices)) if param.choices else ""


def _bounds_cell(param: OpParam) -> str:
    if param.minimum is None and param.maximum is None:
        return ""
    lo = "" if param.minimum is None else str(param.minimum)
    hi = "" if param.maximum is None else str(param.maximum)
    return f"[{lo}, {hi}]"


def _op_produces(spec: OpSpec) -> str:
    return "value" if produces_value_result(spec) else "derived image"


def _render_op(spec: OpSpec) -> str:
    lines = [
        f"#### `{spec.name}` — {spec.summary}",
        "",
        f"*category: `{spec.category}` · produces: {_op_produces(spec)}*",
        "",
    ]
    if spec.params:
        lines.append("| Param | Type | Default | Required | Choices | Bounds | Description |")
        lines.append("|---|---|---|---|---|---|---|")
        for pname, p in spec.params.items():
            default = "" if p.required else _param_cell(p.default)
            required = "yes" if p.required else "no"
            lines.append(
                f"| `{pname}` | `{p.ptype.__name__}` | {default} | {required} | "
                f"{_choices_cell(p)} | {_bounds_cell(p)} | {_cell(p.doc)} |"
            )
    else:
        lines.append("*(no parameters)*")
    lines.append("")
    return "\n".join(lines)


def _render_ops_table() -> str:
    specs = fvops.list_ops()
    lines = [
        "## Operation catalogue",
        "",
        f"{len(specs)} registered operations, grouped by category. Every one is "
        "callable as `img.<name>(**params) -> Result` and via `img.run(name, "
        "**params)` / a recipe step `{'op': name, 'params': {...}}`.",
        "",
    ]
    current_category = None
    for spec in specs:
        if spec.category != current_category:
            current_category = spec.category
            lines.append(f"### {current_category}")
            lines.append("")
        lines.append(_render_op(spec))
    return "\n".join(lines)


def build_markdown() -> str:
    """The full generated document, as a string — pure, no filesystem I/O.
    Used both by ``main()`` (write to disk) and the drift-guard test
    (compare against the committed file without touching it)."""
    header = f"""<!-- AUTO-GENERATED by tools/gen_api_reference.py — do not edit by hand.
     Regenerate: uv run python tools/gen_api_reference.py -->

# fermiviewer.api reference

Generated from the live `fermiviewer.api` module docstring and the ops
registry — a signature or default shown here always matches the
checked-out source. (Deliberately version-free: embedding the release
number made every `chore(release)` version bump stale this file and fail
the drift-guard test on CI — v0.1.23 hit exactly that.) See `examples/`
for complete worked scripts and the top-level `README.md`'s **Scripting**
section for the quickstart and the `fv --script` recipe runner.

{_doc(fvapi)}

---

"""
    body = _render_surface() + "\n---\n\n" + _render_ops_table()
    return header + body + "\n"


def main() -> int:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(build_markdown(), encoding="utf-8")
    print(f"wrote {OUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
