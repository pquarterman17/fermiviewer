"""Analysis algorithms (imaging, EELS, EDS, diffraction).

Pure library layer: ndarrays/DataStruct in, plain results out. No
FastAPI/Pydantic imports allowed here (enforced by
tests/test_repo_integrity.py). Physics constants port verbatim from
fermi-viewer — see PORT_CHECKLIST.md for the do-not-"fix" annotations.
"""
