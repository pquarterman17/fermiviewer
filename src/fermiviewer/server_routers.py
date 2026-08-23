"""Router registration for the FastAPI app — split out of server.py to
respect the 500-line ceiling (same treatment as server_launch.py).

Every route module registers here and ONLY here: server.py calls
`include_all_routers(app)` once during create_app(). Imports stay inside
the function so importing fermiviewer.server (or this module) stays
cheap — route modules pull in numpy/scipy-heavy calc code.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI


def include_all_routers(app: FastAPI) -> None:
    """Attach every route module's router to the app. Routers attach
    here as they land (W5)."""
    from fermiviewer.routes.analysis import router as analysis_router
    from fermiviewer.routes.analysis_wireups import router as wireups_router
    from fermiviewer.routes.batch_ops import router as batch_ops_router
    from fermiviewer.routes.calibration import router as calibration_router
    from fermiviewer.routes.composite import router as composite_router
    from fermiviewer.routes.defect_ops import router as defect_ops_router
    from fermiviewer.routes.dev import router as dev_router
    from fermiviewer.routes.diffraction_setup import router as diffraction_setup_router
    from fermiviewer.routes.distributions import router as distributions_router
    from fermiviewer.routes.eds_advanced import router as eds_advanced_router
    from fermiviewer.routes.eds_maps import router as eds_maps_router
    from fermiviewer.routes.eds_quant import router as eds_quant_router
    from fermiviewer.routes.eds_zeta import router as eds_zeta_router
    from fermiviewer.routes.eels_advanced import router as eels_advanced_router
    from fermiviewer.routes.eels_identify import router as eels_identify_router
    from fermiviewer.routes.eels_maps import router as eels_maps_router
    from fermiviewer.routes.export import router as export_router
    from fermiviewer.routes.export_batch import router as export_batch_router
    from fermiviewer.routes.export_table import router as export_table_router
    from fermiviewer.routes.filter import router as filter_router
    from fermiviewer.routes.folders import router as folders_router
    from fermiviewer.routes.fourd import router as fourd_router
    from fermiviewer.routes.fourd_com import router as fourd_com_router
    from fermiviewer.routes.grains_trained import router as grains_trained_router
    from fermiviewer.routes.images import router as images_router
    from fermiviewer.routes.imaging_ops import router as imaging_ops_router
    from fermiviewer.routes.jobs_api import router as jobs_router
    from fermiviewer.routes.layers import router as layers_router
    from fermiviewer.routes.measure import router as measure_router
    from fermiviewer.routes.montage_compare import router as montage_compare_router
    from fermiviewer.routes.project_io import router as project_io_router
    from fermiviewer.routes.regions import router as regions_router
    from fermiviewer.routes.results_api import router as results_router
    from fermiviewer.routes.session_io import router as session_io_router
    from fermiviewer.routes.shape_id import router as shape_id_router
    from fermiviewer.routes.spectral_fit import router as spectral_fit_router
    from fermiviewer.routes.structure import router as structure_router
    from fermiviewer.routes.structure_grains import router as structure_grains_router
    from fermiviewer.routes.usermeta import router as usermeta_router
    from fermiviewer.routes.watch import router as watch_router

    for _router in (
        images_router, analysis_router, wireups_router, batch_ops_router, measure_router,
        filter_router, export_router, export_batch_router, export_table_router, session_io_router,
        imaging_ops_router, defect_ops_router, structure_router, structure_grains_router,
        grains_trained_router,
        jobs_router, calibration_router, composite_router, dev_router, usermeta_router,
        diffraction_setup_router, spectral_fit_router, eds_advanced_router,
        eds_zeta_router, eds_quant_router, eds_maps_router, eels_advanced_router,
        eels_identify_router, eels_maps_router,
        layers_router, watch_router,
        fourd_router, fourd_com_router, folders_router, regions_router, montage_compare_router,
        project_io_router, distributions_router, shape_id_router, results_router,
    ):
        app.include_router(_router)
