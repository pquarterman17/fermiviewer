"""Capture and structurally validate FermiViewer's UI appearance matrix.

Run with a dev server already listening, or let this script start one. The
browser dependency stays ephemeral so Playwright is not a runtime dependency:

    uv run --with playwright python tools/visual/capture_matrix.py
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "build" / "visual-matrix"
THEMES = ("dark", "light")
ACCENTS = ("violet", "teal", "ocean", "amber", "rose")
COMPACT = {"width": 1024, "height": 768}
FULL = {"width": 1440, "height": 900}
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:5173")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--channel", default="msedge")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument(
        "--no-start-server",
        action="store_true",
        help="fail instead of starting `uv run fv --dev` when URL is unavailable",
    )
    return parser.parse_args()


def url_ready(url: str, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout):  # noqa: S310
            return True
    except (OSError, urllib.error.URLError):
        return False


def ensure_server(url: str, may_start: bool) -> subprocess.Popen[bytes] | None:
    if url_ready(url):
        return None
    if not may_start:
        raise RuntimeError(f"dev server is not reachable at {url}")
    server = subprocess.Popen(  # noqa: S603
        ["uv", "run", "fv", "--dev", "--no-browser", "--no-auto-shutdown"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise RuntimeError("dev server exited before becoming ready")
        if url_ready(url):
            return server
        time.sleep(0.25)
    server.terminate()
    raise TimeoutError(f"dev server did not become ready at {url}")


def stop_server(server: subprocess.Popen[bytes] | None) -> None:
    if server is None:
        return
    server.terminate()
    try:
        server.wait(timeout=10)
    except subprocess.TimeoutExpired:
        server.kill()
        server.wait(timeout=5)


def assert_workspace_fits(page: Any, label: str) -> dict[str, Any]:
    metrics: dict[str, Any] = page.evaluate(
        """() => ({
          width: window.innerWidth,
          height: window.innerHeight,
          scrollWidth: document.documentElement.scrollWidth,
          scrollHeight: document.documentElement.scrollHeight,
          tokens: Object.fromEntries(
            ['--accent', '--accent-text', '--capture', '--text', '--surface-1']
              .map(k => [k, getComputedStyle(document.documentElement)
                .getPropertyValue(k).trim()]))
        })"""
    )
    if metrics["scrollWidth"] > metrics["width"]:
        raise AssertionError(
            f"{label}: horizontal overflow "
            f"{metrics['scrollWidth']} > {metrics['width']}"
        )
    missing = [key for key, value in metrics["tokens"].items() if not value]
    if missing:
        raise AssertionError(f"{label}: unresolved design tokens {missing}")
    if metrics["tokens"]["--accent"] == metrics["tokens"]["--capture"]:
        raise AssertionError(f"{label}: accent and armed-tool capture color collide")
    toolbar = page.locator(".fvd-float-tools").bounding_box()
    if toolbar and toolbar["x"] + toolbar["width"] > metrics["width"] + 0.5:
        raise AssertionError(f"{label}: floating toolbar extends past viewport")
    return metrics


def upload_fixture(page: Any, directory: Path) -> None:
    fixture = directory / "visual-matrix.png"
    fixture.write_bytes(PNG_1PX)
    page.locator('.fvd-menubar input[type="file"]').set_input_files(str(fixture))
    page.wait_for_function(
        "() => window.__fvStore && window.__fvStore.getState().order.length > 0",
        timeout=30_000,
    )
    page.wait_for_timeout(400)


def set_appearance(page: Any, theme: str, accent: str, density: str) -> None:
    page.evaluate(
        """([theme, accent, density]) => {
          const state = window.__fvStore.getState();
          state.setTheme(theme);
          state.setAccent(accent);
          state.setDensity(density);
        }""",
        [theme, accent, density],
    )
    page.wait_for_timeout(75)


def capture(page: Any, out: Path, name: str) -> str:
    filename = f"{name}.png"
    page.screenshot(path=str(out / filename), animations="disabled")
    return filename


def capture_matrix(page: Any, out: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    page.set_viewport_size(COMPACT)
    for theme in THEMES:
        for accent in ACCENTS:
            label = f"compact-{theme}-{accent}"
            set_appearance(page, theme, accent, "compact")
            metrics = assert_workspace_fits(page, label)
            records.append(
                {"surface": label, "file": capture(page, out, label), **metrics}
            )

    page.set_viewport_size(FULL)
    page.evaluate(
        """() => {
          const state = window.__fvStore.getState();
          if (state.leftCol) state.toggleLeft();
          if (state.rightCol) state.toggleRight();
        }"""
    )
    for theme in THEMES:
        label = f"workspace-{theme}-violet"
        set_appearance(page, theme, "violet", "regular")
        metrics = assert_workspace_fits(page, label)
        records.append(
            {"surface": label, "file": capture(page, out, label), **metrics}
        )
    return records


def capture_surfaces(page: Any, out: Path) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for name in ("Image", "Measure"):
        page.get_by_role("menuitem", name=name, exact=True).click()
        menu = page.get_by_role("menu", name=name, exact=True)
        menu.wait_for(state="visible")
        sections = menu.locator(".fvd-menu-section").count()
        submenus = menu.locator('[role="menuitem"][aria-haspopup="menu"]').count()
        if sections + submenus == 0:
            raise AssertionError(f"{name} menu has no visual grouping")
        filename = capture(page, out, f"menu-{name.lower()}")
        records.append({"surface": f"{name} menu", "file": filename})
        page.keyboard.press("Escape")

    target = page.locator('[data-tip="Zoom in"]')
    target.hover()
    page.locator(".fvd-tip").wait_for(state="visible", timeout=2_000)
    records.append(
        {"surface": "hover tooltip", "file": capture(page, out, "tooltip")}
    )
    page.mouse.move(2, 2)
    return records


def run() -> None:
    args = parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    server = ensure_server(args.url, may_start=not args.no_start_server)
    try:
        try:
            # Optional, dev-only dependency: this harness is run on demand
            # with `uv run --with playwright`, never as part of the gate.
            from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is missing; run with `uv run --with playwright ...`"
            ) from exc

        with tempfile.TemporaryDirectory(prefix="fv-visual-") as tmp:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    channel=args.channel, headless=not args.headed
                )
                page = browser.new_page(viewport=FULL)
                browser_errors: list[str] = []
                page.on(
                    "console",
                    lambda msg: browser_errors.append(f"console: {msg.text}")
                    if msg.type == "error"
                    else None,
                )
                page.on("pageerror", lambda error: browser_errors.append(str(error)))
                page.goto(args.url, wait_until="domcontentloaded")
                upload_fixture(page, Path(tmp))
                records = capture_matrix(page, args.out)
                records.extend(capture_surfaces(page, args.out))
                browser.close()

        manifest = {
            "url": args.url,
            "themes": THEMES,
            "accents": ACCENTS,
            "compactViewport": COMPACT,
            "fullViewport": FULL,
            "captures": records,
            "browserErrors": browser_errors,
        }
        (args.out / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        if browser_errors:
            raise AssertionError("browser errors:\n" + "\n".join(browser_errors))
        print(f"visual matrix passed: {len(records)} captures in {args.out}")
    finally:
        stop_server(server)


if __name__ == "__main__":
    run()
