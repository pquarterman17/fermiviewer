# fermiviewer scripting examples

Worked scripts against `fermiviewer.api` — the same headless-capable
Python surface `fv --script` and a Jupyter notebook use. No FastAPI
server, no browser, no GUI: every example is a plain script you run with
`python` or step through cell-by-cell.

## Quickstart

```python
import fermiviewer.api as fv

img = fv.open("scan.dm4")                                  # any registered format
denoised = img.gaussian(sigma=2).image.median(window_size=3).image
stats = denoised.image_stats()
print(stats.value)              # {'mean': ..., 'std': ..., 'min': ..., 'max': ..., 'shape': ...}
csv_bytes = stats.to_csv()      # a one-row CSV, ready to write or upload
print(denoised.methods())       # "scan.dm4 was processed with fermiviewer X.Y.Z:
                                 #  gaussian (sigma=2.0); median (window_size=3)."
```

`fv.open()` returns an `Image`; every registered operation (`fv.ops()`
lists them all) is callable as a method — `img.<op>(**params)` — and
returns a `Result` carrying either a derived `.image` or a plain `.value`.
See `docs/api-reference.md` for the full generated signature/parameter
reference, and the **Scripting** section of the top-level `README.md` for
the `fv --script` no-code recipe runner.

## Examples

| # | File | Needs | What it shows |
|---|------|-------|----------------|
| 1 | [`01_filters_and_roughness.py`](01_filters_and_roughness.py) | nothing (synthesizes its own input) | open → filter chain (`gaussian` → `median`) → `image_stats` / `roughness` → `Result.to_csv()` → methods paragraph + provenance JSON |
| 2 | [`02_eds_quantification.py`](02_eds_quantification.py) | nothing (synthesizes a tiny EDS cube) | build a 2-element EDS spectrum-image → `eds_element_map` per element → `eds_quantify` (Cliff–Lorimer at%/wt%) → export the quant table |
| 3 | [`03_realdata_dm4.py`](03_realdata_dm4.py) | the local-only instrument corpus (`../fermi-viewer` checkout) | the Example 1 recipe run against a real DM4 micrograph; prints a message and exits cleanly (no error) when the corpus isn't present on this machine |

Every example writes its outputs into `./fv_example_output/` (relative to
wherever you run it from) so nothing lands outside a scratch directory.

Run one directly:

```bash
uv run python examples/01_filters_and_roughness.py
```

`tests/test_examples.py` runs Examples 1 and 2 on every `pytest` pass (a
few seconds, no external data) and Example 3 under the `realdata` marker
(skips like every other corpus-dependent test in this repo when the
corpus isn't checked out) — so these scripts can't silently rot.

## Why plain `.py` files, not committed `.ipynb`

This project takes no notebook dependency (no `nbclient`/`jupyter` in any
`pyproject.toml` group), and the size-ratchet/dependency rules here reserve
new runtime and dev deps for things that earn their keep. Each example is
instead written as a **notebook-style cell script**: `# %%` markers divide
it into cells that VS Code, PyCharm, and Jupytext all recognize natively —
open the file and "Run Cell" works with zero extra tooling, no notebook
server required, and the file stays a normal, diffable, `ruff`-checkable
`.py` module. If you want an actual `.ipynb`, `jupytext --to notebook
examples/01_filters_and_roughness.py` produces one without this repo
needing to depend on or maintain that toolchain.
