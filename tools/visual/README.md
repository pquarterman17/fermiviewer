# Visual verification matrix

`capture_matrix.py` turns the recurring UI review pass into a repeatable check.
It uploads a deterministic PNG, captures all five accents in dark and light at
1024×768 compact density, captures both full 1440×900 workspaces, and exercises
the grouped Image menu, Measure menu, and hover tooltip.

```powershell
uv run --with playwright python tools/visual/capture_matrix.py
```

The script reuses an existing dev server or starts `uv run fv --dev` itself. It
uses installed Edge by default; pass `--channel chromium` for a Playwright-managed
browser, or `--executable-path` for a preinstalled browser binary. On Linux
without Edge, for example in a container that ships Chromium:

```bash
uv run --with playwright python tools/visual/capture_matrix.py \
  --executable-path /opt/pw-browsers/chromium-1194/chrome-linux/chrome
```

The browser locale is pinned to `en-US`, so a POSIX system locale such as
`en-US@posix` (which `Intl` rejects) cannot stop the app from rendering. Captures and `manifest.json` land in the gitignored
`build/visual-matrix/` directory.

The command fails for horizontal overflow, a clipped floating toolbar, missing
design tokens, an accent/capture collision, absent menu grouping or tooltip, or
any browser console/page error. The frontend Vitest suite separately pins every
theme/accent and density token block so matrix coverage cannot silently shrink.
