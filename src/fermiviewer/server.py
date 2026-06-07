"""FastAPI app assembly + uvicorn entry point (`uv run fv`)."""

from __future__ import annotations

from fastapi import FastAPI

from fermiviewer import __version__


def create_app() -> FastAPI:
    """Build the FastAPI app. Routers attach here as they land (W5)."""
    from fermiviewer.routes.analysis import router as analysis_router
    from fermiviewer.routes.export import router as export_router
    from fermiviewer.routes.filter import router as filter_router
    from fermiviewer.routes.images import router as images_router
    from fermiviewer.routes.measure import router as measure_router
    from fermiviewer.routes.session_io import router as session_io_router

    app = FastAPI(title="fermiviewer", version=__version__)
    app.include_router(images_router)
    app.include_router(analysis_router)
    app.include_router(measure_router)
    app.include_router(filter_router)
    app.include_router(export_router)
    app.include_router(session_io_router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run("fermiviewer.server:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
