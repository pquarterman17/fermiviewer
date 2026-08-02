"""Example 2 — EDS element maps and Cliff-Lorimer quantification.

Builds a tiny two-element (Fe/Si) EDS spectrum-image cube, opens it
through ``fermiviewer.api`` exactly like a real Bruker BCF/JEOL/EMD/hspy
cube, extracts a per-element map for each line, quantifies the whole
field of view, and exports the result table.

Run directly:

    uv run python examples/02_eds_quantification.py

Outputs land in ``./fv_example_output/`` (relative to your cwd).
"""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import tifffile

import fermiviewer.api as fv
from fermiviewer.calc.eds import line_energy

OUT_DIR = Path("fv_example_output")
OUT_DIR.mkdir(exist_ok=True)

# %% [1] Synthesize a tiny EDS spectrum-image cube ---------------------------
# Peak positions come from the app's OWN line-energy table (calc.eds.
# line_energy) rather than a hand-picked number — the repo's convention for
# any synthetic spectral data (see tools/make_synthetic_si.py), so the
# quantification below lands on the exact windows the real analysis uses.
# This setup is the only part of this example that is not part of the
# fermiviewer.api surface; a real cube skips straight to [2].
H, W, N_CHANNELS = 6, 8, 1200
ENERGY_KEV = 0.01 * np.arange(N_CHANNELS)  # 0.00 .. 11.99 keV
BEAM_KV = 200.0
fe_e, fe_line = line_energy("Fe", beam_kv=BEAM_KV)
si_e, si_line = line_energy("Si", beam_kv=BEAM_KV)
print(f"[1] Fe {fe_line} @ {fe_e:.3f} keV, Si {si_line} @ {si_e:.3f} keV")

# Left half of the field of view is Fe-rich, right half is Si-rich, blended
# across the middle two columns.
si_fraction = np.clip((np.arange(W) - 2.5) / 3.0, 0.0, 1.0)
fe_fraction = 1.0 - si_fraction


def _gaussian_peak(center_kev: float, height: float) -> np.ndarray:
    sigma = 0.03  # keV — a modest detector-resolution stand-in
    return height * np.exp(-((ENERGY_KEV - center_kev) ** 2) / (2.0 * sigma**2))


mean_counts = np.empty((H, W, N_CHANNELS))
for col in range(W):
    spectrum = np.full(N_CHANNELS, 2.0)  # flat background
    spectrum += fe_fraction[col] * _gaussian_peak(fe_e, 60.0)
    spectrum += si_fraction[col] * _gaussian_peak(si_e, 60.0)
    mean_counts[:, col, :] = spectrum
rng = np.random.default_rng(0)
cube = rng.poisson(mean_counts * 50.0).astype(np.uint16)  # realistic shot noise


def _write_hspy_cube(path: Path, data: np.ndarray) -> None:
    """A minimal HyperSpy-layout HDF5 cube — exactly what io/hspy.py reads,
    with array order (y, x, energy) and the energy axis flagged `navigate:
    False` (mirrors tests/test_io_hspy.py's fixture writer)."""
    with h5py.File(path, "w") as f:
        exp = f.create_group("Experiments/eds_cube")
        exp.create_dataset("data", data=data, compression="gzip")
        axes = [
            {"scale": 2.0, "offset": 0.0, "units": "nm", "name": "y", "navigate": True},
            {"scale": 2.0, "offset": 0.0, "units": "nm", "name": "x", "navigate": True},
            {"scale": 0.01, "offset": 0.0, "units": "keV", "name": "Energy", "navigate": False},
        ]
        for i, axis in enumerate(axes):
            group = exp.create_group(f"axis-{i}")
            for key, value in axis.items():
                group.attrs[key] = value


cube_path = OUT_DIR / "synthetic_eds_cube.hspy"
_write_hspy_cube(cube_path, cube)
print(f"[1] wrote synthetic cube -> {cube_path}  shape={cube.shape}")

# %% [2] Open it through the real io path ------------------------------------
img = fv.open(cube_path)
print(f"[2] {img!r}")  # kind == 'spectrum_image'

# %% [3] Per-element maps ------------------------------------------------
half_window = 0.085  # keV — same default eds_quantify uses
fe_map = img.eds_element_map(e_lo=fe_e - half_window, e_hi=fe_e + half_window, bg="linear")
si_map = img.eds_element_map(e_lo=si_e - half_window, e_hi=si_e + half_window, bg="linear")
tifffile.imwrite(OUT_DIR / "fe_map.tif", np.asarray(fe_map.image.to_numpy(), dtype=np.float32))
tifffile.imwrite(OUT_DIR / "si_map.tif", np.asarray(si_map.image.to_numpy(), dtype=np.float32))
print(f"[3] Fe map mean={fe_map.image.to_numpy().mean():.1f}  "
      f"Si map mean={si_map.image.to_numpy().mean():.1f}")

# %% [4] Field-of-view quantification (Cliff-Lorimer at%/wt%) ----------------
quant = img.eds_quantify(elements="Fe,Si")
print("[4] eds_quantify:", quant.value)

# %% [5] Export the quant table ----------------------------------------------
(OUT_DIR / "eds_quant.csv").write_bytes(quant.to_csv())
(OUT_DIR / "eds_quant.json").write_bytes(quant.to_json())
print(f"[5] wrote -> {OUT_DIR}/eds_quant.csv, eds_quant.json")

# %% [6] Provenance for the Fe map's pipeline ---------------------------------
print("[6] methods:", fe_map.image.methods())
(OUT_DIR / "eds_provenance.json").write_text(
    fe_map.image.provenance_json(), encoding="utf-8"
)
