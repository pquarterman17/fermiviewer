"""Example 1 — filter chain, quantitative measurements, and provenance.

The everyday scripting loop against ``fermiviewer.api`` only: open an
image, chain a couple of filter ops, read back quantitative results,
export a table, and print a reproducible methods paragraph. Runs on a
synthesized "AFM-like" height map so it needs no external data and no
GUI — the same recipe works unchanged on a real DM4/TIFF/EMD/... image
(see ``03_realdata_dm4.py``).

Run directly:

    uv run python examples/01_filters_and_roughness.py

Outputs land in ``./fv_example_output/`` (relative to your cwd).

Notebook-style ``# %%`` cells — see examples/README.md for why this repo
ships ``.py`` cell scripts instead of committed ``.ipynb`` files.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import tifffile

import fermiviewer.api as fv

OUT_DIR = Path("fv_example_output")
OUT_DIR.mkdir(exist_ok=True)

# %% [1] Synthesize a tiny input image ---------------------------------------
# Stand-in for a real instrument file — NOT part of the fermiviewer.api
# surface. A real calibrated DM4/TIFF/EMD image loads identically via
# fv.open(); see the corpus-backed version of this same recipe in Example 3.
rng = np.random.default_rng(0)
h, w = 96, 96
yy, xx = np.mgrid[0:h, 0:w]
bumps = sum(
    amp * np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2.0 * sigma**2)))
    for cx, cy, sigma, amp in ((24, 30, 6.0, 40.0), (60, 50, 9.0, 55.0), (75, 20, 4.0, 25.0))
)
surface = (bumps + rng.normal(scale=3.0, size=(h, w))).astype(np.float32)
scan_path = OUT_DIR / "synthetic_scan.tif"
tifffile.imwrite(scan_path, surface)
print(f"[1] wrote synthetic input -> {scan_path}")

# %% [2] Open it through the real io path ------------------------------------
# An explicit Session (rather than the module-level fv.open() shortcut) so
# [6] below can also show the full step log, not just one image's lineage.
session = fv.Session()
img = session.open(scan_path)
print(f"[2] {img!r}")

# %% [3] Chain a filter pipeline ---------------------------------------------
# Every step calls img.<op>(**params) -> Result; .image chains straight into
# the next step, exactly like the GUI's batch recipe runner and `fv --script`.
denoised = img.gaussian(sigma=1.5).image.median(window_size=3).image
print(f"[3] filtered -> {denoised!r}")

# %% [4] Quantitative measurements --------------------------------------------
stats = denoised.image_stats()
roughness = denoised.roughness(level="plane")
print("[4] image_stats:", stats.value)
print("[4] roughness (Ra/Rq/Rz):", {k: roughness.value[k] for k in ("Ra", "Rq", "Rz")})

# %% [5] Export results tables ------------------------------------------------
(OUT_DIR / "image_stats.csv").write_bytes(stats.to_csv())
(OUT_DIR / "roughness.csv").write_bytes(roughness.to_csv())
(OUT_DIR / "roughness.json").write_bytes(roughness.to_json())
print(f"[5] wrote tables -> {OUT_DIR}/image_stats.csv, roughness.csv, roughness.json")

# %% [6] Reproducibility: methods paragraph + provenance --------------------
# denoised.methods() / .provenance_json() walk only the IMAGE-producing steps
# in denoised's own lineage (gaussian -> median) -- exactly what a methods
# section needs. Value-only steps (image_stats, roughness) ran on denoised
# too but produced no new image, so they're outside any image's lineage;
# session.provenance holds the complete, unfiltered log of everything that
# ran, which is what `fv --script` writes to <stem>.provenance.json.
methods = denoised.methods()
(OUT_DIR / "methods.md").write_text(methods + "\n", encoding="utf-8")
(OUT_DIR / "provenance.json").write_text(denoised.provenance_json(), encoding="utf-8")
(OUT_DIR / "session_log.json").write_text(session.provenance.to_json(), encoding="utf-8")
print("[6] methods:", methods)

# %% [7] Optional visualization (matplotlib is not a project dependency) -----
try:
    import matplotlib

    matplotlib.use("Agg")  # headless — no display needed to run this example
    import matplotlib.pyplot as plt
except ImportError:
    print("[7] matplotlib not installed - skipping the preview plot (optional).")
else:
    fig, axes = plt.subplots(1, 2, figsize=(6, 3))
    axes[0].imshow(img.to_numpy(), cmap="gray")
    axes[0].set_title("raw")
    axes[1].imshow(denoised.to_numpy(), cmap="gray")
    axes[1].set_title("gaussian -> median")
    for ax in axes:
        ax.axis("off")
    fig.tight_layout()
    preview_path = OUT_DIR / "preview.png"
    fig.savefig(preview_path, dpi=110)
    plt.close(fig)
    print(f"[7] wrote preview -> {preview_path}")
