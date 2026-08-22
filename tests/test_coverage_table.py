"""docs/operation-coverage.md must match its generator (roadmap item 3A).

Same pattern as tests/test_api_reference.py: the committed audit is
byte-compared against an in-memory regeneration, so a new route, a new op,
or an edited classification cannot leave the published parity table stale.
The generator itself fails on an unclassified analysis-prefix route, so
this test failing is always "regenerate or classify", never a judgement
call.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from gen_coverage_table import OUT_PATH, build_markdown  # noqa: E402


def test_coverage_doc_matches_generator() -> None:
    assert OUT_PATH.is_file(), (
        "docs/operation-coverage.md is missing — run `uv run python tools/gen_coverage_table.py`"
    )
    committed = OUT_PATH.read_text(encoding="utf-8")
    generated = build_markdown()
    assert committed == generated, (
        "docs/operation-coverage.md is stale — regenerate with "
        "`uv run python tools/gen_coverage_table.py` (or classify the "
        "route/op change that produced this drift)"
    )


def test_coverage_generator_is_deterministic() -> None:
    """Byte-identical across runs — what makes the drift guard above a
    guard rather than a flake."""
    assert build_markdown() == build_markdown()
