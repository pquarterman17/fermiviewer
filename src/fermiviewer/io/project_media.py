"""Per-image auxiliary artifacts a save decides on: thumbnail bytes (plan
#37) and the optional sha256 (plan #38).

Split out of `project_file.py` to keep that module's core job — the ZIP
container itself — under the size ratchet as these two features landed.
Both follow the SAME rule `project_paths.reference` uses for `rel`: recompute
when a fresh value is available, otherwise preserve whatever the image
already carried, so an unavailable placeholder's thumbnail and hash both
survive a re-save exactly like its reference does (ADR 0002 §4).
"""

from __future__ import annotations

from fermiviewer.calc.thumbnail import render_thumbnail_png
from fermiviewer.io import project_paths as paths
from fermiviewer.io.project_manifest import ProjectImage

__all__ = ["sha256_for", "thumbnail_bytes"]


def thumbnail_bytes(img: ProjectImage) -> bytes | None:
    """The PNG to write to `thumbs/<id>.png`, or None to write nothing.

    ADR 0002 §2: thumbnails are embedded in BOTH payload modes, for every
    image, regardless of whether its pixels are embedded or referenced —
    unlike pixel embedding, this does not depend on the payload mode.

    Freshly rendered whenever pixels are available (so a recalibration or a
    live edit is reflected); carried over verbatim otherwise. None only when
    there was never a thumbnail to have — a brand new placeholder, or a kind
    with no raster (a 1D spectrum).
    """
    if img.data is not None:
        return render_thumbnail_png(img.data, img.kind)
    return img.thumb


def sha256_for(img: ProjectImage, hash_sources: bool) -> str | None:
    """The sha256 to write to `images[].sha256` (plan #38).

    Freshly computed only when `hash_sources` is True AND a source is
    actually available; otherwise whatever was already carried. This
    parameter only controls whether a NEW hash is computed, never whether an
    old one is dropped.
    """
    if hash_sources:
        source = paths.existing_file(paths.absolute_source(img))
        if source is not None:
            fresh = paths.content_hash(source)
            if fresh is not None:
                return fresh
    return img.sha256
