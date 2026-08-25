"""Interactive grain-label edits — the composition `/api/grains/edit` and
its op both run (ADR 0005 §1).

A separate module because `calc/grains.py` is at 453/500 lines and this is
~60 more; the primitives it composes (`split_grain`,
`enforce_connected_grains`) stay there.

Pure library: numpy + stdlib.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.grains import enforce_connected_grains, split_grain

__all__ = ["GrainEdit", "clip_clicks", "edit_grains", "merge_labels_at"]


def clip_clicks(
    points: Sequence[tuple[float, float]], shape: tuple[int, ...]
) -> list[tuple[int, int]]:
    """``(x, y)`` 0-based clicks -> in-bounds ``(row, col)``, order kept.

    ``int(round(...))`` is Python's banker's rounding (half-to-even: 2.5->2
    but 3.5->4). That is what the GUI has always done, so it is copied
    exactly — ``np.round`` and ``int(x + 0.5)`` disagree with it at .5 and
    would move a click onto a neighbouring grain.

    Order is load-bearing: `split` acts on the FIRST surviving click.
    """
    h, w = int(shape[0]), int(shape[1])
    out: list[tuple[int, int]] = []
    for x, y in points:
        row, col = int(round(y)), int(round(x))
        if 0 <= row < h and 0 <= col < w:
            out.append((row, col))
    return out


def merge_labels_at(
    labels: np.ndarray, clicks_rc: Sequence[tuple[int, int]]
) -> np.ndarray:
    """Merge every distinct positive label under ``clicks_rc`` into the
    lowest of them, rewriting BY LABEL across the whole image (background 0
    is ignored).

    By label, not by connected component — so merging two non-adjacent
    grains does not fuse them into one region. `edit_grains` then re-runs
    `enforce_connected_grains`, which splits the disconnected pieces back
    apart and renumbers. That interaction IS the semantics: the pair comes
    back as two grains with fresh ids, not one.
    """
    ids = {int(labels[r, c]) for r, c in clicks_rc if labels[r, c] > 0}
    if len(ids) < 2:
        raise ValueError("merge needs ≥2 distinct grains")
    keep = min(ids)
    out = labels.copy()
    for label in ids:
        out[labels == label] = keep
    return out


@dataclass(frozen=True)
class GrainEdit:
    """An applied edit: the connectivity-enforced, 1..N-renumbered labels
    and the verb, which callers append to the map's recorded method."""

    labels: np.ndarray
    op: str  # "merge" | "split"


def edit_grains(
    labels: np.ndarray,
    image: np.ndarray,
    op: str,
    points: Sequence[tuple[float, float]],
    *,
    granularity: float = 0.03,
) -> GrainEdit:
    """Apply one interactive edit to a grain-label map.

    ``labels`` and ``image`` must be the same shape — the label map and the
    intensity raster it was derived from. Nothing checked that before this
    lift (the route fetched them from two different session entries), and a
    mismatch would surface as an obscure index error inside the watershed.
    """
    labels = np.asarray(labels, dtype=np.int64)
    image = np.asarray(image)
    if labels.shape[:2] != image.shape[:2]:
        raise ValueError(
            f"label map {labels.shape[:2]} and image {image.shape[:2]} "
            f"must have the same shape"
        )
    if op not in ("merge", "split"):
        raise ValueError("op must be 'merge' or 'split'")

    clicks = clip_clicks(points, labels.shape)
    if not clicks:
        raise ValueError("no points inside the image")

    if op == "merge":
        edited = merge_labels_at(labels, clicks)
    else:
        gid = int(labels[clicks[0]])
        if gid <= 0:
            raise ValueError("click is not on a grain")
        edited = split_grain(labels, image, gid, granularity=granularity)

    # every grain must be one connected region: a merge of non-adjacent
    # grains, or a split, must not leave a label spanning separate pieces
    return GrainEdit(enforce_connected_grains(edited), op)
