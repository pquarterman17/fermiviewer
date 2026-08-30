"""Label-producing analyses over a canonical region.

Spectra (4C-1) and statistics (4C-2) REDUCE over the selected pixels, so a
mask is just a `where=` argument. Segmentation does not: it produces a
label image the same shape as its input, and restricting it raises two
questions those waves never had to answer.

**Which pixels may carry a label.** Only selected ones. `place_labels`
clears everything outside the mask, so no particle or grain leaks across a
region boundary. That is the rule a caller can rely on, and it is what
makes a hole a real hole rather than a decorative outline.

**Which pixels inform the analysis.** Not the same set, and pretending
otherwise would be the quiet kind of wrong. A threshold is a function of
the selected VALUES, so `region_values` hands them over exactly and the
caller passes the result in — an out-of-region blob inside the bounding
box then cannot move the threshold. But a texture feature, a gradient, or
a watershed basin is a function of a pixel NEIGHBOURHOOD, and a
neighbourhood does not stop at a region edge. Those algorithms read the
bounding-box crop, because the alternative — filling the outside with
some neutral value — invents an edge exactly where the region boundary
is, and every gradient-based method would then find a boundary there.

So the contract is: **labels are exact, context is the bounding box.**
For a rectangular region the two coincide, which is why the legacy
`extract_rect_roi`/`embed_rect_roi` path is a special case of this one
rather than a thing being replaced. For an irregular region the
difference is real, so the ops record it in provenance
(`label_context: "bounding-box"`) instead of leaving a reader to assume
the stronger claim.

Relabeling is conditional for the same reason. Renumbering survivors
1..n is required once masking has punched holes in the label set — a
table indexed by label would otherwise carry empty rows — but doing it
unconditionally would renumber a plain rectangular run whose labels
already had gaps from `min_area` filtering, silently changing an answer
this wave is supposed to preserve. So `place_labels` renumbers only when
the mask actually cleared a labelled pixel.
"""

from __future__ import annotations

import numpy as np

from fermiviewer.calc.roi import RectRoi, roi_slices

__all__ = ["place_labels", "place_values", "region_values"]


def _crop(shape: tuple[int, ...], rect: RectRoi | None) -> tuple[slice, slice]:
    return roi_slices(shape, rect)


def region_values(
    values: np.ndarray, rect: RectRoi | None = None, mask: np.ndarray | None = None
) -> np.ndarray:
    """The selected pixels of `values`, flattened, in row-major order.

    `rect` is 1-based inclusive (``None`` = the whole image) and `mask` is
    a FULL-IMAGE boolean array or ``None`` meaning every pixel of `rect` —
    the pairing `region_resolve.ResolvedRegion` hands out, so a caller
    holding a resolved region feeds this and `calc.region_stats` the same
    two values without reshaping anything.

    Use it for a threshold: Otsu over these is Otsu over the region, where
    Otsu over the bounding-box crop would let a bright feature the user
    deliberately excluded set the level for the pixels they kept.
    """
    rows, cols = _crop(values.shape, rect)
    block = values[rows, cols]
    if mask is None:
        return np.asarray(block).reshape(-1)
    window = mask[rows, cols]
    if window.shape != block.shape:
        raise ValueError(
            f"mask window {window.shape} does not match the rect {block.shape}"
        )
    return np.asarray(block[window]).reshape(-1)


def place_labels(
    labels: np.ndarray,
    shape: tuple[int, int],
    rect: RectRoi | None = None,
    mask: np.ndarray | None = None,
) -> tuple[np.ndarray, bool]:
    """Crop-local `labels` as a full-image label map, region-clipped.

    `labels` is the segmenter's output over the `rect` crop. Returns the
    full-image map (0 = background outside the region) and whether the
    labels were RENUMBERED — which is the honest signal that the mask
    removed something, and is what the ops report as `region_clipped`.

    Renumbering is skipped when the mask clears nothing, so a rectangular
    region reproduces `calc.roi.embed_rect_roi` exactly, gaps in the
    incoming label numbering included.
    """
    rows, cols = _crop(shape, rect)
    expected = (rows.stop - rows.start, cols.stop - cols.start)
    if labels.shape != expected:
        raise ValueError(f"label block {labels.shape} does not match the rect {expected}")
    block = np.asarray(labels)
    if block.min() < 0:
        raise ValueError("labels must be non-negative (0 = background)")

    clipped = False
    if mask is not None:
        window = mask[rows, cols]
        if window.shape != block.shape:
            raise ValueError(
                f"mask window {window.shape} does not match the rect {block.shape}"
            )
        # `clipped` asks whether a LABELLED pixel was dropped, not whether
        # the mask is smaller than its box: clearing only background
        # changes no answer and must not renumber anything.
        clipped = bool(np.any(block[~window] != 0))
        if clipped:
            block = np.where(window, block, 0)

    if clipped:
        block = _renumber(block)

    out = np.zeros(tuple(shape), dtype=block.dtype)
    out[rows, cols] = block
    return out, clipped


def _renumber(block: np.ndarray) -> np.ndarray:
    """Survivors renumbered 1..n, ascending, gap-free.

    A lookup table rather than `np.unique(..., return_inverse=True)`.
    The inverse would also be correct as called from `place_labels`, since
    clipping is what triggers renumbering and clipping always leaves a 0
    behind for the inverse to map to 0. But that correctness is an
    accident of the caller rather than a property of this function, and a
    later caller renumbering a block with no background would silently get
    everything shifted down by one. The table states the mapping outright.
    """
    kept = np.unique(block)
    kept = kept[kept != 0]
    lut = np.zeros(int(block.max()) + 1, dtype=block.dtype)
    lut[kept] = np.arange(1, kept.size + 1, dtype=block.dtype)
    return np.asarray(lut[block])


def place_values(
    values: np.ndarray,
    shape: tuple[int, int],
    rect: RectRoi | None = None,
    mask: np.ndarray | None = None,
    fill: float = 0.0,
) -> np.ndarray:
    """Crop-local `values` as a full-image array, region-cleared.

    The counterpart to `place_labels` for arrays whose numbers MEAN
    something fixed — a class id, a probability, an orientation — where
    renumbering would be corruption rather than tidying. A trained
    preview's class map is the case in point: turning class 3 into class 2
    because class 2 fell outside the region would silently relabel the
    specimen.

    Outside the region the array takes `fill`, because a pixel that was
    not analyzed has no class and no confidence, and reporting the
    segmenter's guess there would be a claim the region says was not made.
    """
    rows, cols = _crop(shape, rect)
    expected = (rows.stop - rows.start, cols.stop - cols.start)
    block = np.asarray(values)
    if block.shape != expected:
        raise ValueError(f"value block {block.shape} does not match the rect {expected}")
    if mask is not None:
        window = mask[rows, cols]
        if window.shape != block.shape:
            raise ValueError(
                f"mask window {window.shape} does not match the rect {block.shape}"
            )
        block = np.where(window, block, block.dtype.type(fill))
    out = np.full(tuple(shape), block.dtype.type(fill), dtype=block.dtype)
    out[rows, cols] = block
    return out
