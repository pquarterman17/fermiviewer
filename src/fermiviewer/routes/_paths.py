"""HTTP wrapper around `io.user_paths` — the path policy as a 422.

The policy itself lives in `io.user_paths` so the pure I/O layer stays
importable without FastAPI. Routes want the same two calls but with a
`PathPolicyError` already turned into the 4xx the rest of the surface
promises, and a refused path is a bad request, never a 500.
"""

from __future__ import annotations

from fastapi import HTTPException

from fermiviewer.io.user_paths import (
    PathPolicyError,
    safe_data_path,
    safe_data_paths,
)

__all__ = ["checked_data_path", "checked_data_paths"]


def checked_data_path(raw: str, *, where: str) -> str:
    """Canonicalise one user-named path; 422 if the policy refuses it."""
    try:
        return safe_data_path(raw, where=where)
    except PathPolicyError as e:
        raise HTTPException(422, str(e)) from None


def checked_data_paths(raws: list[str], *, where: str) -> list[str]:
    """Canonicalise a list of user-named paths; 422 naming the bad index."""
    try:
        return safe_data_paths(raws, where=where)
    except PathPolicyError as e:
        raise HTTPException(422, str(e)) from None
