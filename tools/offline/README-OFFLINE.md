# FermiViewer — offline / air-gapped install

FermiViewer is a local web app for electron-microscopy image analysis:
TEM/STEM image viewing, EELS / EDS / diffraction analysis, measurements,
and image processing. It runs entirely on this machine and opens in your
browser — no data ever leaves the computer.

This folder is a self-contained FermiViewer install kit. It needs **no
internet, no Node.js, no compiler, and no admin rights** on this machine —
only a 64-bit Python. Everything installs into this folder; nothing else
on the system is touched.

## What's inside

| File | Purpose |
|---|---|
| `install.py` | the installer — Python standard library only |
| `wheelhouse/` | FermiViewer + every dependency as pre-built wheels |
| `requirements.txt` | the exact pinned versions (for IT / security review) |
| `bundle-info.json` | which OS, CPU, and Python versions this kit covers |

## Requirements

- The OS and CPU this bundle was built for — see `bundle-info.json`
  (the file name also says, e.g. `fv-offline-windows-x64`).
- A 64-bit **Python** matching one of the versions in `bundle-info.json`
  (typically 3.10–3.14). No Python on the machine? The full installer
  from python.org runs fine without internet — a per-user install
  (no admin) is enough.

## Install

1. Extract the zip anywhere you have write access (e.g. `C:\FermiViewer`
   or `~/fermiviewer`).
2. From inside the extracted folder run:

   ```
   Windows:      py install.py
   macOS/Linux:  python3 install.py
   ```

3. Launch:

   ```
   Windows:      FermiViewer.bat      (double-click works)
   macOS/Linux:  ./fermiviewer
   ```

   The app serves itself at <http://127.0.0.1:8000> and opens your
   browser; it shuts down by itself when the last tab closes. Pass a
   folder to start browsing there: `FermiViewer.bat C:\data\session-42`.

## Update / uninstall

- **Update:** extract a newer bundle and run its `install.py` — or copy a
  newer `wheelhouse/` over this one and re-run `install.py` here.
- **Uninstall:** delete this folder. That's all of it.

## Troubleshooting

- *"you are running Python X.Y, but this bundle covers …"* — launch the
  installer with a covered interpreter, e.g. `py -3.13 install.py`
  (Windows) or `python3.13 install.py`.
- *`ensurepip`/venv errors on Debian/Ubuntu* — `install.py` bootstraps
  pip from the wheelhouse automatically; if it still fails, install the
  `python3-venv` OS package from your offline package mirror.
- *Port 8000 already in use* — FermiViewer steps to the next free port
  automatically and prints the URL.

## How this bundle was made

On an internet-connected machine, from the FermiViewer source tree:

```
uv run python tools/offline/make_bundle.py
```

That builds the web frontend once, packs it inside the `fermiviewer`
wheel, and downloads the pinned dependency wheels from PyPI for each
covered Python version. See `tools/offline/make_bundle.py` in the source
repository.
