"""User-facing wording for operation summaries and parameter docs.

An op's ``summary`` and a param's ``doc`` are written for developers: they
name the calc function behind the op ("calc/stack.align_stack"), ADR
sections and how the HTTP route differs. The batch palette showed all of
that to users. The registry keeps the developer text (it documents the
code); the palette serves this trimmed form: developer-only parentheticals
and sentences dropped, and a summary cut to its first clause.
"""

from __future__ import annotations

import re

__all__ = ["user_doc", "user_summary"]

_DEV = re.compile(
    r"calc[/.]|\bADR\b|§|\.py\b|\.m\b|\broutes?\b|\bio\.|`|\bMATLAB\b|"
    r"\bport\b|\bmirror(?:ed)?\b|\bop\b|\bops\b|\bcalc\b|\bwave-[A-Z]\b|session image"
)
#: a snake_case identifier -- a field or function name, not prose
_SNAKE = re.compile(r"\b[a-z][a-z0-9]*_[a-z0-9_]+\b")
_SEPARATORS = (". ", "; ", " — ", " -- ")


def _clauses(text: str) -> list[str]:
    """`text` split at top-level sentence/clause separators (never inside
    parentheses), each clause keeping no trailing separator."""
    out: list[str] = []
    depth, start, i = 0, 0, 0
    while i < len(text):
        ch = text[i]
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        elif depth == 0:
            sep = next((s for s in _SEPARATORS if text.startswith(s, i)), None)
            if sep == ". " and text[max(0, i - 3):i] in ("e.g", "i.e", " vs"):
                sep = None  # an abbreviation, not the end of a sentence
            if sep is not None:
                out.append(text[start:i])
                i += len(sep)
                start = i
                continue
        i += 1
    out.append(text[start:])
    return [c.strip() for c in out if c.strip()]


def _drop_dev_parentheticals(text: str) -> str:
    """Remove every top-level ``( ... )`` group that mentions developer
    internals, with the space before it."""
    out: list[str] = []
    depth, group = 0, ""
    for ch in text:
        if depth == 0 and ch != "(":
            out.append(ch)
            continue
        group += ch
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                if not (_DEV.search(group) or _SNAKE.search(group)):
                    out.append(group)
                group = ""
    out.append(group)  # an unbalanced tail stays as written
    return re.sub(r"\s+([,.;:])", r"\1", re.sub(r"\s{2,}", " ", "".join(out))).strip()


def user_summary(text: str) -> str:
    """The first clause of an op summary, without developer references; a
    ": detail" tail that names code (snake_case fields, calc paths) goes too."""
    clauses = _clauses(text)
    first = _drop_dev_parentheticals(clauses[0] if clauses else text)
    head, colon, tail = first.partition(": ")
    if colon and (_DEV.search(tail) or _SNAKE.search(tail)):
        first = head
    return first.rstrip(" .:,") or text


def user_doc(text: str) -> str:
    """A param doc without the clauses and parentheticals that only make
    sense to someone reading the code."""
    kept = [c for c in _clauses(_drop_dev_parentheticals(text)) if not _DEV.search(c)]
    return "; ".join(kept)
