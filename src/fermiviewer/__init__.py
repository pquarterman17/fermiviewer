"""fermiviewer — electron-microscopy image analysis.

Python/FastAPI port of fermi-viewer (MATLAB). Layering contract:

    io/     pure library: file bytes -> DataStruct (no HTTP, no Pydantic)
    calc/   pure library: ndarrays/DataStruct in -> results out (same rule)
    routes/ thin FastAPI adapters over io/ and calc/
    server  app assembly + uvicorn entry point

io/ and calc/ must never import fastapi, pydantic, or anything from
routes/ — that isolation is what keeps their tests server-free.
"""

__version__ = "0.1.21"
