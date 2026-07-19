"""Appearance matrix contracts shared by UI review and screenshot tooling."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
THEME_CSS = (ROOT / "frontend" / "src" / "theme.css").read_text(encoding="utf-8")
SHELL_CSS = (
    ROOT / "frontend" / "src" / "styles" / "theme-web" / "01-shell-library.css"
).read_text(encoding="utf-8")
THEMES = ("dark", "light")
ACCENTS = ("violet", "teal", "ocean", "amber", "rose")
DENSITIES = ("compact", "regular", "comfy")
ACCENT_TOKENS = ("--accent", "--accent-soft", "--accent-text")
DENSITY_TOKENS = ("--pad", "--pad-lg", "--row-h", "--font-size", "--font-size-sm")


def _block(selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{([^}}]*)\}}", THEME_CSS)
    assert match is not None, f"missing CSS selector {selector}"
    return match.group(1)


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("accent", ACCENTS)
def test_every_theme_accent_pair_defines_the_ramp(theme: str, accent: str) -> None:
    block = _block(f'[data-theme="{theme}"][data-accent="{accent}"]')
    for token in ACCENT_TOKENS:
        assert f"{token}:" in block


@pytest.mark.parametrize("density", DENSITIES)
def test_every_density_defines_layout_tokens(density: str) -> None:
    block = _block(f'[data-density="{density}"]')
    for token in DENSITY_TOKENS:
        assert f"{token}:" in block


def _token(block: str, token: str) -> str:
    """The declared value of `token`, so tests compare colors, not presence."""
    match = re.search(rf"{re.escape(token)}\s*:\s*([^;]+);", block)
    assert match is not None, f"missing token {token}"
    return match.group(1).strip().lower()


@pytest.mark.parametrize("theme", THEMES)
def test_amber_keeps_capture_feedback_distinct(theme: str) -> None:
    # Amber is the accent most likely to collide with the amber capture cue.
    # Asserting only that the tokens EXIST would still pass if --capture were
    # set to the accent color outright, which is the failure this guards.
    block = _block(f'[data-theme="{theme}"][data-accent="amber"]')
    assert _token(block, "--capture") != _token(block, "--accent")
    assert _token(block, "--capture-soft") != _token(block, "--accent-soft")


def test_disabled_menu_entries_do_not_receive_hover_accent() -> None:
    """Disabled native and class-based menu entries stay visually muted."""
    assert ".fvd-menu-entry:not(:disabled):not(.disabled):hover" in SHELL_CSS
    assert not re.search(r"(?m)^\.fvd-menu-entry:hover\s*\{", SHELL_CSS)
