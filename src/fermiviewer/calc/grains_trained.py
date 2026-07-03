"""Scribble-trained grain segmentation — ported from
imaging.grains.trainFromScribbles / segmentTrained (the ilastik/Weka-style
interactive classifier).

The user paints a few strokes labelling pixels by class; a softmax
classifier is fit on the multi-scale feature stack at only the labelled
pixels (`train_from_scribbles`), then applied to every pixel and split into
connected grains (`segment_trained`). The feature stack and connected-
components labelling are shared verbatim with the unsupervised
`segment_auto` path — the two modes differ only in clustering vs. classifying.

Kept out of grains.py to stay under the 500-line module ceiling.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.forest import (
    RandomForestModel,
    forest_predict,
    forest_train,
)
from fermiviewer.calc.grains import extract_grain_features
from fermiviewer.calc.ml import SoftmaxModel, softmax_predict, softmax_train
from fermiviewer.calc.segment import label_components

__all__ = [
    "TrainedGrainModel",
    "TrainedPreview",
    "TrainedSegmentation",
    "preview_trained",
    "rasterize_strokes",
    "segment_trained",
    "train_from_scribbles",
]


@dataclass(frozen=True)
class TrainedGrainModel:
    """A fitted classifier plus the feature configuration it was trained on,
    so `segment_trained` rebuilds the identical feature space (the image it
    is applied to may differ from the one it was trained on). ``classifier``
    selects which predict path `segment_trained` dispatches to."""

    model: SoftmaxModel | RandomForestModel
    scales: tuple[float, ...]
    gradient_sigma: float
    classifier: str = "softmax"


@dataclass(frozen=True)
class TrainedSegmentation:
    labels: np.ndarray  # (H, W) grain label map, 0 = boundary/dropped
    n_grains: int
    class_map: np.ndarray  # (H, W) predicted class per pixel
    max_prob: np.ndarray  # (H, W) winning-class probability (confidence)
    classes: np.ndarray


def train_from_scribbles(
    img: np.ndarray,
    label_mask: np.ndarray,
    scales: tuple[float, ...] = (2.0, 4.0),
    gradient_sigma: float = 0.0,
    classifier: str = "softmax",
    learn_rate: float = 0.5,
    max_iter: int = 800,
    lambda_: float = 1e-3,
    n_trees: int = 64,
    max_depth: int = 14,
    seed: int = 0,
) -> TrainedGrainModel:
    """Fit a pixel classifier from sparse class labels — ported.

    label_mask: (H, W) integer image, 0 = unlabelled, positive ints = class
    id. Only nonzero pixels are training samples; needs ≥2 distinct classes.

    classifier: ``"softmax"`` (linear, ported) or ``"forest"`` (nonlinear
    random forest, Quick-Wins #8). The forest captures texture classes that
    are not linearly separable in the multi-scale feature stack.
    """
    img = np.asarray(img, dtype=np.float64)
    label_mask = np.asarray(label_mask)
    if img.shape != label_mask.shape:
        raise ValueError(
            f"img is {img.shape} but label_mask is {label_mask.shape}."
        )
    if classifier not in ("softmax", "forest"):
        raise ValueError(f"unknown classifier {classifier!r}.")
    labeled = label_mask > 0
    if not labeled.any():
        raise ValueError("label_mask has no labelled (nonzero) pixels.")
    if np.unique(label_mask[labeled]).size < 2:
        raise ValueError("need at least 2 distinct classes in label_mask.")

    feats = extract_grain_features(
        img, scales=scales, gradient_sigma=gradient_sigma
    )
    h, w, f = feats.shape
    x = feats.reshape(h * w, f)
    idx = labeled.reshape(-1)
    x_train = x[idx]
    y_train = label_mask.reshape(-1)[idx]
    model: SoftmaxModel | RandomForestModel
    if classifier == "forest":
        model = forest_train(
            x_train, y_train, n_trees=n_trees, max_depth=max_depth, seed=seed
        )
    else:
        model = softmax_train(
            x_train,
            y_train,
            learn_rate=learn_rate,
            max_iter=max_iter,
            lambda_=lambda_,
        )
    return TrainedGrainModel(
        model=model,
        scales=scales,
        gradient_sigma=gradient_sigma,
        classifier=classifier,
    )


@dataclass(frozen=True)
class TrainedPreview:
    """The pixel-classification result *before* grains are labelled — used by
    the optional non-committing preview: which class each pixel got and what
    fraction of the image each class covers. No connected-components step, so
    it is cheaper than `segment_trained` and never registers a label map."""

    class_map: np.ndarray  # (H, W) predicted class per pixel
    classes: np.ndarray  # sorted unique class ids the model knows
    fractions: dict[int, float]  # class id → fraction of pixels (0..1)


def preview_trained(
    img: np.ndarray,
    model: TrainedGrainModel,
    features: np.ndarray | None = None,
) -> TrainedPreview:
    """Classify every pixel with a trained model and report the per-class
    pixel composition — the classify half of `segment_trained`, without the
    connected-components grain labelling. Lets the UI show how the paint
    strokes generalize before committing to segmentation."""
    if features is None:
        feats = extract_grain_features(
            img, scales=model.scales, gradient_sigma=model.gradient_sigma
        )
    else:
        feats = np.asarray(features, dtype=np.float64)
    h, w, f = feats.shape
    x = feats.reshape(h * w, f)

    if model.classifier == "forest":
        cls, _ = forest_predict(model.model, x)  # type: ignore[arg-type]
    else:
        cls, _ = softmax_predict(model.model, x)  # type: ignore[arg-type]
    class_map = cls.reshape(h, w)

    total = float(class_map.size)
    fractions = {
        int(c): float(np.count_nonzero(class_map == c)) / total
        for c in model.model.classes
    }
    return TrainedPreview(
        class_map=class_map,
        classes=model.model.classes,
        fractions=fractions,
    )


def segment_trained(
    img: np.ndarray,
    model: TrainedGrainModel,
    features: np.ndarray | None = None,
    boundary_class: Sequence[int] = (),
    min_area: int = 25,
    connectivity: int = 8,
) -> TrainedSegmentation:
    """Classify every pixel with a trained model, then label connected
    components within each (non-boundary) class as individual grains —
    ported. Mirrors segment_auto's component-labelling exactly."""
    if features is None:
        feats = extract_grain_features(
            img, scales=model.scales, gradient_sigma=model.gradient_sigma
        )
    else:
        feats = np.asarray(features, dtype=np.float64)
    h, w, f = feats.shape
    x = feats.reshape(h * w, f)

    if model.classifier == "forest":
        cls, probs = forest_predict(model.model, x)  # type: ignore[arg-type]
    else:
        cls, probs = softmax_predict(model.model, x)  # type: ignore[arg-type]
    class_map = cls.reshape(h, w)
    max_prob = probs.max(axis=1).reshape(h, w)

    boundary = set(int(b) for b in boundary_class)
    labels = np.zeros((h, w), dtype=np.int64)
    g = 0
    for c in model.model.classes:
        if int(c) in boundary:
            continue
        mask = class_map == c
        if not mask.any():
            continue
        lc, nc = label_components(mask, connectivity)
        for j in range(1, nc + 1):
            comp = lc == j
            if comp.sum() >= min_area:
                g += 1
                labels[comp] = g

    return TrainedSegmentation(
        labels=labels,
        n_grains=g,
        class_map=class_map,
        max_prob=max_prob,
        classes=model.model.classes,
    )


def _stamp_disk(
    mask: np.ndarray, cx: float, cy: float, radius: int, cls: int
) -> None:
    """Paint a filled disk of `cls` into mask, operating only on the disk's
    bounding box (so the cost is O(r²) per stamp, not O(H·W))."""
    h, w = mask.shape
    x0, x1 = max(0, int(cx) - radius), min(w - 1, int(cx) + radius)
    y0, y1 = max(0, int(cy) - radius), min(h - 1, int(cy) + radius)
    if x1 < x0 or y1 < y0:
        return
    ys = np.arange(y0, y1 + 1)[:, None]
    xs = np.arange(x0, x1 + 1)[None, :]
    disk = (xs - cx) ** 2 + (ys - cy) ** 2 <= radius * radius
    mask[y0 : y1 + 1, x0 : x1 + 1][disk] = cls


def rasterize_strokes(
    shape: tuple[int, int],
    strokes: Sequence[dict],
) -> np.ndarray:
    """Rasterize painted polyline strokes into a (H, W) class-label mask
    (0 = unlabelled). Each stroke is a dict with keys ``class_id`` (int ≥1),
    ``radius`` (brush radius, px) and ``points`` ([[x, y], ...] image
    coords). Segments are densified at ~radius/2 spacing so a fast drag
    paints a continuous band, matching the MATLAB brush-disk behaviour."""
    h, w = shape
    mask = np.zeros((h, w), dtype=np.int64)
    for st in strokes:
        cls = int(st["class_id"])
        radius = max(0, int(round(float(st["radius"]))))
        pts = st["points"]
        prev: tuple[float, float] | None = None
        for pt in pts:
            x, y = float(pt[0]), float(pt[1])
            if prev is not None:
                px, py = prev
                dist = math.hypot(x - px, y - py)
                steps = max(1, int(dist / max(radius * 0.5, 1.0)))
                for s in range(1, steps):
                    t = s / steps
                    _stamp_disk(mask, px + (x - px) * t, py + (y - py) * t, radius, cls)
            _stamp_disk(mask, x, y, radius, cls)
            prev = (x, y)
    return mask
