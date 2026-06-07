"""File-format parsers (DM3/DM4, BCF, SER, MRC, TIFF, RAW).

Pure library layer: bytes/paths in, DataStruct out. No FastAPI/Pydantic
imports allowed here (enforced by tests/test_repo_integrity.py).

All parsers register in registry.py exactly once (single-registration
rule); ambiguous extensions add a content sniffer.
"""
