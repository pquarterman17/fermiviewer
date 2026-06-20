# PyInstaller spec — self-contained FermiViewer server sidecar.
# Build (from the repo root, frontend/dist already built):
#   uv run pyinstaller tools/bundle/fv-server.spec --noconfirm
# Output: dist/fv-server/ (one-dir; ~250 MB — scipy/numpy BLAS).

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parents[1]  # noqa: F821 — SPECPATH is injected

a = Analysis(  # noqa: F821
    [str(ROOT / "tools" / "bundle" / "fv_entry.py")],
    pathex=[str(ROOT / "src")],
    datas=[
        # the SPA, served by the sidecar at / (frozen-aware lookup in
        # server._frontend_dist)
        (str(ROOT / "frontend" / "dist"), "frontend/dist"),
        # OFL-licensed JetBrains Mono TTF for baked scale-bar labels
        # (frozen-aware lookup in fermiviewer.assets.fonts)
        (str(ROOT / "src" / "fermiviewer" / "assets" / "fonts"), "fermiviewer/assets/fonts"),
    ],
    hiddenimports=[
        # uvicorn's dynamically-imported workers/loops
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
        # the *.auto dispatchers above import these concrete protocol impls
        # in a try/except; pin them so the frozen build can't end up without
        # an HTTP/WebSocket transport (the /api/ws lifecycle socket would
        # silently fail). wsproto_impl is omitted — wsproto isn't installed.
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.http.httptools_impl",
        "uvicorn.protocols.websockets.websockets_impl",
        "uvicorn.protocols.websockets.websockets_sansio_impl",
    ],
    excludes=[
        # dev/test-only heavyweights that must never ride along
        "pytest", "mypy", "ruff", "PyInstaller",
        "rsciio", "hyperspy", "exspy",
        "tkinter", "matplotlib", "IPython",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="fv-server",
    console=True,   # console=True: logs visible when run standalone;
    icon=None,      # the Tauri shell spawns it CREATE_NO_WINDOW anyway
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    name="fv-server",
)
