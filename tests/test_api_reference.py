"""Drift guard for docs/api-reference.md (Scripting #11).

The committed file must always match what tools/gen_api_reference.py
currently produces from fermiviewer.api + the ops registry. A mismatch
means fermiviewer.api, an op's schema, or the docs file itself changed
without regenerating -- fix it with:

    uv run python tools/gen_api_reference.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))


def test_api_ref_doc_matches_generator() -> None:
    from gen_api_reference import OUT_PATH, build_markdown

    assert OUT_PATH.is_file(), (
        f"{OUT_PATH} is missing -- generate it with "
        "`uv run python tools/gen_api_reference.py`"
    )
    committed = OUT_PATH.read_text(encoding="utf-8")
    generated = build_markdown()
    assert committed == generated, (
        "docs/api-reference.md is stale relative to fermiviewer.api / the ops "
        "registry -- regenerate with `uv run python tools/gen_api_reference.py` "
        "and commit the result."
    )


def test_api_ref_generator_is_deterministic() -> None:
    """Two runs against the same source must be byte-identical -- this is
    what makes the drift-guard test above meaningful rather than flaky."""
    from gen_api_reference import build_markdown

    assert build_markdown() == build_markdown()
