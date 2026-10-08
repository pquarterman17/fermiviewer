// Two-point tools (distance, profile, arrow, box, circle) place by a drag as
// well as by click-click: the tooltips promised "drag on the image", but a
// drag used to register only the first point and leave the capture pending.

import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CaptureMode } from "../../store/viewer";
import type { PendingMeasure } from "./pointerDecisions";
import { useStagePointers, type StagePointersCtx } from "./useStagePointers";

// z = 1, vp/view offsets 0 → image px == client px
function mkCtx(captureMode: CaptureMode): StagePointersCtx {
  const wrap = {
    getBoundingClientRect: () => ({ left: 0, top: 0 }) as DOMRect,
  } as unknown as HTMLDivElement;
  const ctx = {
    wrapRef: { current: wrap },
    scaleBarRef: { current: null as unknown as HTMLDivElement },
    dragRef: { current: null },
    specnavRef: { current: false },
    fourdnavRef: { current: false },
    paintingRef: { current: false },
    view: { z: 1, px: 0, py: 0 },
    imgSize: { w: 1_000_000, h: 1_000_000 },
    vp: { w: 0, h: 0 },
    activeId: "img",
    captureMode,
    panTool: false,
    spaceHeld: false,
    paintActive: false,
    grainMode: "off",
    isGrainMap: false,
    fixedZoomW: 256,
    fixedZoomH: 256,
    pending: null,
    marquee: null,
    grainPending: null,
    setCaptureMode: vi.fn(),
    setStatus: vi.fn(),
    setPanning: vi.fn(),
    setCursor: vi.fn(),
    setSpecnavPixel: vi.fn(),
    setFourdNavPixel: vi.fn(),
    setMarquee: vi.fn(),
    setPending: vi.fn(),
    setGrainPending: vi.fn(),
    setStageCtx: vi.fn(),
    startStroke: vi.fn(),
    addPoint: vi.fn(),
    apply: vi.fn(),
    finalizeMeasure: vi.fn(),
    finalizeCalibration: vi.fn(),
    finalizeBoxProfile: vi.fn(),
  } as StagePointersCtx;
  ctx.setPending = vi.fn((p) => {
    ctx.pending = p as PendingMeasure | null;
  });
  return ctx;
}

function ev(clientX: number, clientY: number) {
  return {
    clientX,
    clientY,
    button: 0,
    shiftKey: false,
    pointerId: 1,
    currentTarget: {
      setPointerCapture: () => {},
      releasePointerCapture: () => {},
    },
    preventDefault: () => {},
  } as unknown as React.PointerEvent;
}

describe("useStagePointers — two-point tools", () => {
  it.each(["distance", "profile", "arrow", "box", "circle"] as const)(
    "%s: a drag places both points",
    (mode) => {
      const ctx = mkCtx(mode);
      const { result, rerender } = renderHook(() => useStagePointers(ctx));
      act(() => result.current.onPointerDown(ev(100, 100)));
      rerender();
      act(() => result.current.onPointerMove(ev(150, 120)));
      rerender();
      act(() => result.current.onPointerUp(ev(200, 140)));
      expect(ctx.finalizeMeasure).toHaveBeenCalledWith(mode, [
        { x: 100, y: 100 },
        { x: 200, y: 140 },
      ]);
    },
  );

  it("click-click still works (a release in place keeps the capture pending)", () => {
    const ctx = mkCtx("distance");
    const { result, rerender } = renderHook(() => useStagePointers(ctx));
    act(() => result.current.onPointerDown(ev(100, 100)));
    rerender();
    act(() => result.current.onPointerUp(ev(101, 100)));
    expect(ctx.finalizeMeasure).not.toHaveBeenCalled();
    expect(ctx.pending?.pts).toHaveLength(2); // committed point + live cursor
    rerender();
    act(() => result.current.onPointerDown(ev(300, 100)));
    rerender();
    act(() => result.current.onPointerUp(ev(300, 100)));
    expect(ctx.finalizeMeasure).toHaveBeenCalledTimes(1);
    expect(ctx.finalizeMeasure).toHaveBeenCalledWith("distance", [
      { x: 100, y: 100 },
      { x: 300, y: 100 },
    ]);
  });
});
