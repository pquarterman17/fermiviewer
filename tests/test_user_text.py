"""The batch palette shows users op summaries and param docs; the registry's
developer wording (calc paths, ADR sections, route notes) must not leak."""

from __future__ import annotations

import re

from fermiviewer.routes._user_text import user_doc, user_summary
from fermiviewer.routes.batch_ops import batch_operations

_LEAK = re.compile(r"calc/|\bADR\b|§|`|\.py\b")


def test_summary_keeps_the_first_clause_without_code_references() -> None:
    assert user_summary(
        "FFT cross-correlation drift correction across a stack; the subject "
        "is the reference frame (calc/stack.align_stack)"
    ) == "FFT cross-correlation drift correction across a stack"
    assert user_summary(
        "Axis-aligned box integrated along both axes → horizontal (x, over "
        "columns) profiles (calc/profile_stats.box_integrate). Corners are 1-based"
    ) == "Axis-aligned box integrated along both axes → horizontal (x, over columns) profiles"
    assert user_summary("Gaussian blur") == "Gaussian blur"


def test_doc_drops_developer_clauses_but_keeps_e_g() -> None:
    assert user_doc(
        "Gaussian mask radius (FFT px); 0 = auto (min(|g1|,|g2|)/3, the calc's "
        "own sentinel)"
    ) == "Gaussian mask radius (FFT px); 0 = auto"
    assert user_doc("comma-separated values, e.g. '1,2'") == "comma-separated values, e.g. '1,2'"


def test_palette_serves_no_developer_references() -> None:
    for op in batch_operations()["operations"]:
        assert not _LEAK.search(op["summary"]), (op["name"], op["summary"])
        for param in op["params"]:
            assert not _LEAK.search(param["doc"]), (op["name"], param["name"], param["doc"])
