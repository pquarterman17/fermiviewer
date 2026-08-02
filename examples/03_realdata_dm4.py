"""Example 3 — the same filter/roughness recipe against a real DM4.

Repeats Example 1's open -> filter chain -> quantitative measurements ->
export flow, but on a REAL micrograph from the local-only instrument
corpus this repo's ``realdata``-marked tests use (see
``fermiviewer.devsamples`` / ``tests/conftest.py``). That corpus lives in
the sibling ``fermi-viewer`` MATLAB checkout and is never required to run
Examples 1 or 2 — this script auto-skips with a clear, printed message
(exit code 0, not an error) when it isn't present on this machine.

Run directly:

    uv run python examples/03_realdata_dm4.py

Outputs land in ``./fv_example_output/`` (relative to your cwd).
"""

from __future__ import annotations

from pathlib import Path

import fermiviewer.api as fv
from fermiviewer.devsamples import corpus_root, find_sample_files

OUT_DIR = Path("fv_example_output")
OUT_DIR.mkdir(exist_ok=True)

# %% [1] Locate a real corpus file, or skip gracefully -----------------------
# find_sample_files is the SAME helper `fv --dev`'s auto-load testing mode
# uses to locate a real per-extension sample — it never raises, just returns
# an empty list when the corpus isn't checked out on this machine.
samples = find_sample_files((".dm4",))
if not samples:
    print(
        "Real-instrument corpus not found on this machine -- skipping.\n"
        f"Looked under: {corpus_root()}\n"
        "This example needs the sibling fermi-viewer MATLAB repo's committed\n"
        "corpus (see fermiviewer.devsamples.corpus_root(); set FV_MATLAB_ROOT\n"
        "to point at a different checkout). Examples 1 and 2 need no corpus."
    )
    raise SystemExit(0)

dm4_path = samples[0]
print(f"[1] found real corpus file -> {dm4_path}")

# %% [2] Open it through the real io path ------------------------------------
img = fv.open(dm4_path)
print(f"[2] {img!r}")

# %% [3] The same filter chain as Example 1 ----------------------------------
denoised = img.gaussian(sigma=1.0).image.median(window_size=3).image
print(f"[3] filtered -> {denoised!r}")

# %% [4] Quantitative measurements --------------------------------------------
stats = denoised.image_stats()
roughness = denoised.roughness(level="plane")
print("[4] image_stats:", stats.value)
print("[4] roughness (Ra/Rq/Rz):", {k: roughness.value[k] for k in ("Ra", "Rq", "Rz")})

# %% [5] Export results + provenance -----------------------------------------
(OUT_DIR / "realdata_image_stats.csv").write_bytes(stats.to_csv())
(OUT_DIR / "realdata_roughness.csv").write_bytes(roughness.to_csv())
methods = denoised.methods()
(OUT_DIR / "realdata_methods.md").write_text(methods + "\n", encoding="utf-8")
print("[5] methods:", methods)
