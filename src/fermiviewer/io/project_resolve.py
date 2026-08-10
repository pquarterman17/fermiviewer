"""Turning a project's stored reference back into pixels (ADR 0002 §3/§5a).

Split out of `project_file.py` because the *same* resolution has to happen
twice, at different times:

* on **load**, against the ADR's root order (hint, then the project's own
  directory);
* on a **later user re-point** (plan #34/#35), against a folder the user
  picks — invokable at any time and repeatable, since samples that moved to
  different folders each need their own pick.

Keeping one implementation means a re-pointed image is resolved by exactly
the rules the original load used, including §5a's "the manifest wins":
only the pixels come from disk, so a recalibration done in the app is not
silently reverted by whatever the file still claims.

Nothing here raises for a missing, foreign, unreadable or mismatched file —
that is a placeholder, never an error (ADR 0002 §4). Untrusted input is
assumed: callers pass a `rel` that `safe_posix_rel` has already vetted.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.io.project_manifest import ProjectImage
from fermiviewer.io.project_paths import existing_file
from fermiviewer.io.registry import load_auto

__all__ = ["Resolution", "fits", "parse_source", "resolve"]


@dataclass(frozen=True)
class Resolution:
    """What trying to resolve one reference produced.

    `image` is None when nothing usable was found. `found` records a file
    that *existed* at the reference even when it turned out to hold
    something else — the difference between "your folder is wrong" and "your
    folder holds different data" is exactly what the user needs told.
    """

    image: ProjectImage | None = None
    found: Path | None = None
    #: The file's actual size when it differs from the recorded `size_bytes`
    #: (ADR 0002 §3's cheap sanity check). Reported, never enforced.
    size_bytes: int | None = None

    @property
    def mismatched(self) -> bool:
        return self.size_bytes is not None


def fits(data: np.ndarray, kind: DataKind, axes: Sequence[AxisCal]) -> bool:
    """Whether an array is what the manifest says it is — DataStruct's own
    invariants: dimensionality for the kind, one axis per dimension,
    non-empty."""
    try:
        DataStruct(data=data, kind=kind, axes=tuple(axes))
    except (ValueError, KeyError):
        return False
    return True


def parse_source(
    source: Path, kind: DataKind, axes: Sequence[AxisCal]
) -> np.ndarray | None:
    """Pixels from a referenced file, or None if it is not what we expect.

    Only the pixels come from disk: kind, calibration and metadata stay as
    the manifest recorded them, so a recalibration done in the app survives a
    light save. Any parser failure degrades to an unavailable placeholder —
    one unreadable source must never make a whole project unloadable.
    """
    try:
        ds = load_auto(source)
    except Exception:  # noqa: BLE001 - see docstring: degrade, never fail the load
        return None
    data = np.asarray(ds.data)
    return data if fits(data, kind, axes) else None


def _size_mismatch(expected: int | None, found: Path) -> int | None:
    if expected is None:
        return None
    try:
        actual = found.stat().st_size
    except OSError:
        return None
    return None if actual == expected else actual


def resolve(img: ProjectImage, roots: Sequence[Path]) -> Resolution:
    """Try `root / img.rel` for each root in order, first match wins.

    `roots` is `project_paths.search_roots()` plus any root the user has
    re-pointed this session, appended — the ADR's order is preserved rather
    than replaced, so a hint that starts working again (a remounted drive)
    still wins over a stale manual pick.

    A root whose file exists but does not describe this image is recorded and
    skipped, so one stale copy early in the order cannot mask the real data
    later in it.
    """
    if not img.rel:
        return Resolution()
    seen: Path | None = None
    for root in roots:
        found = existing_file(root / img.rel)
        if found is None:
            continue
        seen = seen or found
        data = parse_source(found, img.kind, img.axes)
        if data is None:
            continue
        return Resolution(
            image=replace(
                img,
                data=data,
                embedded=False,
                unavailable=False,
                resolved_path=str(found),
            ),
            found=found,
            size_bytes=_size_mismatch(img.size_bytes, found),
        )
    return Resolution(found=seen)
