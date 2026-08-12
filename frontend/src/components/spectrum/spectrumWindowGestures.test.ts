import { fireEvent } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";

import type { SpeciesWindows } from "../../lib/spectrum/species";
import {
  attachWindowGestures,
  type WindowGesturePlot,
} from "./spectrumWindowGestures";

// Identity plot: 1 energy unit = 1 CSS px, and jsdom's zero-sized
// getBoundingClientRect makes clientX the plot-relative position directly.
function makePlot(): { plot: WindowGesturePlot; host: HTMLElement } {
  const host = document.createElement("div");
  const over = document.createElement("div");
  host.appendChild(over);
  document.body.appendChild(host);
  return {
    host,
    plot: {
      over,
      posToVal: (px: number) => px,
      valToPos: (v: number) => v,
    },
  };
}

describe("attachWindowGestures", () => {
  let host: HTMLElement;
  let plot: WindowGesturePlot;
  let windows: SpeciesWindows;
  let onLive: Mock<(w: SpeciesWindows) => void>;
  let onCommit: Mock<(w: SpeciesWindows) => void>;
  let uplotSpy: Mock<() => void>;
  let detach: () => void;

  beforeEach(() => {
    ({ host, plot } = makePlot());
    windows = { signal: { lo: 30, hi: 70 } };
    onLive = vi.fn((w: SpeciesWindows) => {
      windows = w; // parent state loop: live updates feed getWindows
    });
    onCommit = vi.fn();
    // stands in for uPlot's own zoom-select mousedown on `.u-over`
    uplotSpy = vi.fn();
    plot.over.addEventListener("mousedown", uplotSpy);
    detach = attachWindowGestures(plot, host, {
      getWindows: () => windows,
      onLive,
      onCommit,
      nudgeStep: () => 1,
    });
  });

  afterEach(() => {
    detach();
    host.remove();
  });

  it("claims an edge drag before uPlot's zoom sees the mousedown", () => {
    fireEvent.mouseDown(plot.over, { clientX: 69, button: 0 });
    expect(uplotSpy).not.toHaveBeenCalled();

    fireEvent.mouseMove(document, { clientX: 80 });
    expect(onLive).toHaveBeenLastCalledWith({ signal: { lo: 30, hi: 80 } });
    expect(plot.over.style.cursor).toBe("ew-resize");

    fireEvent.mouseUp(document);
    expect(onCommit).toHaveBeenCalledWith({ signal: { lo: 30, hi: 80 } });
    expect(plot.over.style.cursor).toBe("");
  });

  it("slides the body from the grab point", () => {
    fireEvent.mouseDown(plot.over, { clientX: 50, button: 0 });
    expect(uplotSpy).not.toHaveBeenCalled();
    expect(plot.over.style.cursor).toBe("grabbing");

    fireEvent.mouseMove(document, { clientX: 60 });
    expect(onLive).toHaveBeenLastCalledWith({ signal: { lo: 40, hi: 80 } });
  });

  it("falls through to uPlot away from the window", () => {
    fireEvent.mouseDown(plot.over, { clientX: 10, button: 0 });
    expect(uplotSpy).toHaveBeenCalledTimes(1);

    fireEvent.mouseMove(document, { clientX: 20 });
    fireEvent.mouseUp(document);
    expect(onLive).not.toHaveBeenCalled();
    expect(onCommit).not.toHaveBeenCalled();
  });

  it("never claims a shift-drag — that gesture draws a new window", () => {
    fireEvent.mouseDown(plot.over, { clientX: 69, button: 0, shiftKey: true });
    expect(uplotSpy).toHaveBeenCalledTimes(1);
    expect(onCommit).not.toHaveBeenCalled();
  });

  it("shows resize and grab cursors on hover", () => {
    fireEvent.mouseMove(plot.over, { clientX: 69 });
    expect(plot.over.style.cursor).toBe("ew-resize");
    fireEvent.mouseMove(plot.over, { clientX: 50 });
    expect(plot.over.style.cursor).toBe("grab");
    fireEvent.mouseMove(plot.over, { clientX: 10 });
    expect(plot.over.style.cursor).toBe("");
  });

  it("nudges with arrows, coarsely with shift, committing on key-up", () => {
    fireEvent.keyDown(host, { key: "ArrowRight" });
    expect(onLive).toHaveBeenLastCalledWith({ signal: { lo: 31, hi: 71 } });
    fireEvent.keyDown(host, { key: "ArrowRight" });
    expect(onLive).toHaveBeenLastCalledWith({ signal: { lo: 32, hi: 72 } });
    expect(onCommit).not.toHaveBeenCalled();

    fireEvent.keyUp(host, { key: "ArrowRight" });
    expect(onCommit).toHaveBeenCalledWith({ signal: { lo: 32, hi: 72 } });

    fireEvent.keyDown(host, { key: "ArrowLeft", shiftKey: true });
    expect(onLive).toHaveBeenLastCalledWith({ signal: { lo: 22, hi: 62 } });
  });

  it("stops arrow keys from reaching the app's global hotkeys", () => {
    const global = vi.fn();
    document.addEventListener("keydown", global);
    fireEvent.keyDown(host, { key: "ArrowRight" });
    expect(global).not.toHaveBeenCalled();
    document.removeEventListener("keydown", global);
  });

  it("makes the host focusable and focuses it on claim", () => {
    expect(host.tabIndex).toBe(0);
    fireEvent.mouseDown(plot.over, { clientX: 69, button: 0 });
    expect(document.activeElement).toBe(host);
  });

  it("detaches completely", () => {
    detach();
    fireEvent.mouseDown(plot.over, { clientX: 69, button: 0 });
    expect(uplotSpy).toHaveBeenCalledTimes(1);
    fireEvent.mouseMove(document, { clientX: 80 });
    expect(onLive).not.toHaveBeenCalled();
    detach = () => {}; // afterEach double-detach guard
  });
});
