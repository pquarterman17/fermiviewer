"""Provenance log — per-result parameters + input lineage (Scripting #5).

The reproducibility record a methods section needs, hung off the op
vocabulary: every op that produces or derives an image records a
``ProvenanceStep`` (op, resolved params, input id(s) + source, output id,
fermiviewer version, ISO timestamp). ``ProvenanceLog`` keys steps by produced
image and walks the lineage to reconstruct a result's full ancestry, exporting
machine JSON or a methods-paragraph Markdown.

Pure layer (datastruct/stdlib only). Timestamps come from the caller (or
``datetime.now``) so tests stay deterministic.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from fermiviewer import __version__

__all__ = ["ProvenanceLog", "ProvenanceStep"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class ProvenanceStep:
    """One recorded operation in a pipeline."""

    op: str
    params: dict[str, Any]
    label: str
    inputs: tuple[str, ...]  # input image id(s)
    output: str | None  # produced image id (None for value-only ops)
    input_names: tuple[str, ...] = ()
    value: Any = None  # scalar/table result for value ops
    version: str = __version__
    timestamp: str = field(default_factory=_utc_now)


class ProvenanceLog:
    """An append-only log of ``ProvenanceStep``s plus the produced-image
    lineage, so any result's full ancestry chain can be reconstructed."""

    def __init__(self) -> None:
        self._steps: list[ProvenanceStep] = []
        self._by_output: dict[str, ProvenanceStep] = {}

    def record(self, step: ProvenanceStep) -> ProvenanceStep:
        self._steps.append(step)
        if step.output is not None:
            self._by_output[step.output] = step
        return step

    @property
    def steps(self) -> list[ProvenanceStep]:
        return list(self._steps)

    def ancestry(self, image_id: str) -> list[ProvenanceStep]:
        """The ordered chain of steps that produced ``image_id`` (root → leaf).

        Follows the first input of each producing step up the lineage; stops at
        an opened (un-produced) image. Guards against cycles."""
        chain: list[ProvenanceStep] = []
        seen: set[str] = set()
        cur: str | None = image_id
        while cur is not None and cur in self._by_output and cur not in seen:
            seen.add(cur)
            step = self._by_output[cur]
            chain.append(step)
            cur = step.inputs[0] if step.inputs else None
        chain.reverse()
        return chain

    def to_json(self, image_id: str | None = None) -> str:
        """JSON of the full log, or just ``image_id``'s ancestry."""
        steps = self.ancestry(image_id) if image_id else self._steps
        return json.dumps([asdict(s) for s in steps], indent=2)

    def to_markdown(self, image_id: str) -> str:
        """A methods paragraph for ``image_id``'s pipeline.

        e.g. "<name> was processed with fermiviewer X.Y.Z: gaussian
        (sigma=2.0); median (window_size=3)."
        """
        chain = self.ancestry(image_id)
        if not chain:
            return f"No recorded provenance for {image_id}."
        root_name = chain[0].input_names[0] if chain[0].input_names else "the input"
        version = chain[-1].version
        verbs = "; ".join(_describe(s) for s in chain)
        return (
            f"{root_name} was processed with fermiviewer {version}: {verbs}."
        )


def _describe(step: ProvenanceStep) -> str:
    if step.params:
        ps = ", ".join(f"{k}={v}" for k, v in step.params.items())
        return f"{step.label} ({ps})"
    return step.label
