// LASSO_EDITING_PLAN Wave 2 item B: capture stays fine, simplify at close.
// Pins the wiring that lives in useStagePointers.ts's onPointerUp lasso
// branch — regionCapture.ts stays pure (regionCapture.test.ts covers it
// unchanged) and simplifyRing.ts stays pure (simplifyRing.test.ts covers
// the algorithm) — this file exercises only the SEAM: the fixed 1
// screen-px capture floor, and the close-time
// `simplifyRing(pts, prefs.lassoCloseSimplifyPx / view.z)` call, driven through
// the hook's real pointer handlers so the assertions are on what actually
// reaches finalizeMeasure — the store/finalize path, not a render.

import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULTS, savePrefs } from "../../lib/prefs";

vi.mock("../../lib/simplifyRing", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("../../lib/simplifyRing")>();
  return { ...actual, simplifyRing: vi.fn(actual.simplifyRing) };
});

import { simplifyRing } from "../../lib/simplifyRing";
import type { PendingMeasure } from "./pointerDecisions";
import type { Pt } from "./stageUtils";
import { useStagePointers, type StagePointersCtx } from "./useStagePointers";

const simplifyRingSpy = vi.mocked(simplifyRing);

// z = screen px per image px; vp = {0,0} and view.px/py = 0 make
// screenToImage collapse to `ip = clientXY / z` — see lib/geometry.ts.
function mkCtx(overrides: Partial<StagePointersCtx> = {}): StagePointersCtx {
  const wrap = {
    getBoundingClientRect: () => ({ left: 0, top: 0 }) as DOMRect,
  } as unknown as HTMLDivElement;
  return {
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
    captureMode: "lasso",
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
    ...overrides,
  };
}

function fakeEvent(clientX: number, clientY: number) {
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

describe("useStagePointers — lasso simplify-at-close (item B)", () => {
  beforeEach(() => {
    localStorage.clear();
    simplifyRingSpy.mockClear();
  });

  it("captures a dense circular stroke and closes to a small STORED vertex count (mutation: drop the simplifyRing call → hundreds of pts)", () => {
    savePrefs({ ...DEFAULTS, lassoCloseSimplifyPx: 2 });
    const ctx = mkCtx();
    ctx.setPending = vi.fn((p) => {
      ctx.pending = p as PendingMeasure | null;
    });
    const { result, rerender } = renderHook(() => useStagePointers(ctx));

    const cx = 5000;
    const cy = 5000;
    const R = 200;
    const N = 2500; // arc spacing ~0.5 image-px — well under the 1px floor
    act(() => {
      result.current.onPointerDown(fakeEvent(cx + R, cy));
    });
    rerender();
    for (let i = 1; i <= N; i++) {
      const a = (2 * Math.PI * i) / N;
      act(() => {
        result.current.onPointerMove(
          fakeEvent(cx + R * Math.cos(a), cy + R * Math.sin(a)),
        );
      });
    }
    act(() => {
      result.current.onPointerUp(fakeEvent(cx + R, cy));
    });

    expect(ctx.finalizeMeasure).toHaveBeenCalledTimes(1);
    const [kind, pts] = (ctx.finalizeMeasure as ReturnType<typeof vi.fn>).mock
      .calls[0] as [string, Pt[]];
    expect(kind).toBe("lasso");
    // captured (pre-simplify) points were in the hundreds-to-low-thousands
    // (one per ~1 image-px of a 2*pi*200 circumference); the STORED,
    // simplified ring collapses that to a small handful of vertices.
    expect(pts.length).toBeGreaterThanOrEqual(3);
    expect(pts.length).toBeLessThan(60);
    expect(simplifyRingSpy).toHaveBeenCalledTimes(1);
  });

  it("a deliberate spike survives close (Convention 2: deviation > epsilon retained; mutation: swap simplifyRing for a naive `pts.slice(0, 20)` decimation → the spike, captured well past index 20, is dropped)", () => {
    savePrefs({ ...DEFAULTS, lassoCloseSimplifyPx: 2 }); // eps = 2 image px at z=1
    const ctx = mkCtx();
    ctx.setPending = vi.fn((p) => {
      ctx.pending = p as PendingMeasure | null;
    });
    const { result, rerender } = renderHook(() => useStagePointers(ctx));

    const cx = 5000;
    const cy = 5000;
    const R = 200;
    const N = 800; // spacing ~1.57 image-px — every raw sample is kept
    const spikeAt = Math.floor(N / 4);
    const spikeR = R + 80; // deviation ~80 image px >> eps=2

    act(() => {
      result.current.onPointerDown(fakeEvent(cx + R, cy));
    });
    rerender();
    for (let i = 1; i <= N; i++) {
      const a = (2 * Math.PI * i) / N;
      const r = i === spikeAt ? spikeR : R;
      act(() => {
        result.current.onPointerMove(
          fakeEvent(cx + r * Math.cos(a), cy + r * Math.sin(a)),
        );
      });
    }
    act(() => {
      result.current.onPointerUp(fakeEvent(cx + R, cy));
    });

    const [, pts] = (ctx.finalizeMeasure as ReturnType<typeof vi.fn>).mock
      .calls[0] as [string, Pt[]];
    // real Douglas–Peucker simplification happened (count collapsed well
    // below the ~800 captured points) AND the deliberate large deviation
    // is still present in the STORED ring — a naive decimation (e.g. "keep
    // every Nth point" instead of calling simplifyRing) would also shrink
    // the count but has no reason to land on the spike's exact index, so
    // this pair of assertions together catches that class of mutation.
    expect(pts.length).toBeGreaterThanOrEqual(3);
    expect(pts.length).toBeLessThan(60);
    const maxDistFromCenter = Math.max(
      ...pts.map((p) => Math.hypot(p.x - cx, p.y - cy)),
    );
    expect(maxDistFromCenter).toBeGreaterThan(R + 40);
  });

  it("polygon tool pts are byte-identical through close — lasso-only (Convention 5; mutation: run finalizeMeasure's polygon path through simplifyRing too → the near-collinear vertex gets dropped)", () => {
    const ctx = mkCtx({ captureMode: "polygon" });
    ctx.setPending = vi.fn((p) => {
      ctx.pending = p as PendingMeasure | null;
    });
    const { result, rerender } = renderHook(() => useStagePointers(ctx));

    // 4 vertices; ip2 sits ~0.1 image-px off the ip1–ip3 chord — well
    // under lassoCloseSimplifyPx's default epsilon (2) — so if simplification
    // wrongly ran here, ip2 would be dropped and this test would go RED.
    const ip1: Pt = { x: 1000, y: 1000 };
    const ip2: Pt = { x: 1300, y: 1000.1 };
    const ip3: Pt = { x: 1600, y: 1000 };
    const ip4: Pt = { x: 1300, y: 1600 };
    const closeClick: Pt = { x: 1002, y: 1001 }; // within POLY_CLOSE_PX(8) of ip1

    for (const p of [ip1, ip2, ip3, ip4, closeClick]) {
      act(() => {
        result.current.onPointerDown(fakeEvent(p.x, p.y));
      });
      rerender();
    }

    expect(ctx.finalizeMeasure).toHaveBeenCalledTimes(1);
    const [kind, pts] = (ctx.finalizeMeasure as ReturnType<typeof vi.fn>).mock
      .calls[0] as [string, Pt[]];
    expect(kind).toBe("polygon");
    expect(pts).toEqual([ip1, ip2, ip3, ip4]);
    expect(simplifyRingSpy).not.toHaveBeenCalled();
  });

  it("capture step filter is fixed at 1 screen-px regardless of the pref (mutation: read lassoCloseSimplifyPx back into the capture tol → 1.5px-apart points get dropped)", () => {
    savePrefs({ ...DEFAULTS, lassoCloseSimplifyPx: 5 }); // coarsest legal value (0.5-5 range), still coarser than 1px
    const ctx = mkCtx();
    ctx.setPending = vi.fn((p) => {
      ctx.pending = p as PendingMeasure | null;
    });
    const { result, rerender } = renderHook(() => useStagePointers(ctx));

    act(() => {
      result.current.onPointerDown(fakeEvent(1000, 1000));
    });
    rerender();
    // each move is 1.5 screen-px further along x than the last KEPT point
    // — under the old pref-driven (20px) filter every one of these would
    // be dropped; the fixed 1px floor accepts them all.
    const drops: number[] = [];
    for (let i = 1; i <= 5; i++) {
      act(() => {
        result.current.onPointerMove(fakeEvent(1000 + i * 1.5, 1000));
      });
      drops.push((ctx.pending as PendingMeasure).pts.length);
    }
    act(() => {
      result.current.onPointerUp(fakeEvent(1000 + 5 * 1.5, 1000));
    });

    // seed point + 5 accepted moves = 6 points captured, all kept
    expect(drops.at(-1)).toBe(6);
    const [, pts] = (ctx.finalizeMeasure as ReturnType<typeof vi.fn>).mock
      .calls[0] as [string, Pt[]];
    // simplifyRing may still merge near-collinear points at close, but the
    // CAPTURE side must not have thrown any of the 6 away before that —
    // asserted directly via the epsilon-argument pin below and via the
    // pending trace above (`drops`), which is the pre-simplify capture.
    expect(pts.length).toBeGreaterThanOrEqual(3);
  });

  it("epsilon honours zoom: the same stroke closed at z=4 passes epsilon/4 (image space) to simplifyRing, vs z=1 passing epsilon (mutation: compute epsilon without dividing by view.z → both calls get the same value)", () => {
    savePrefs({ ...DEFAULTS, lassoCloseSimplifyPx: 2 });
    const stroke: Pt[] = [
      { x: 5000, y: 5000 },
      { x: 5100, y: 5000 },
      { x: 5100, y: 5100 },
      { x: 5000, y: 5100 },
    ];

    const runAt = (z: number) => {
      const ctx = mkCtx({ view: { z, px: 0, py: 0 } });
      ctx.setPending = vi.fn((p) => {
        ctx.pending = p as PendingMeasure | null;
      });
      const { result, rerender } = renderHook(() => useStagePointers(ctx));
      // screenToImage: ip = screenXY / z, so screen coords are image*z
      act(() => {
        result.current.onPointerDown(
          fakeEvent(stroke[0].x * z, stroke[0].y * z),
        );
      });
      rerender();
      for (const p of stroke.slice(1)) {
        act(() => {
          result.current.onPointerMove(fakeEvent(p.x * z, p.y * z));
        });
      }
      act(() => {
        result.current.onPointerUp(
          fakeEvent(stroke[0].x * z, stroke[0].y * z),
        );
      });
    };

    simplifyRingSpy.mockClear();
    runAt(1);
    expect(simplifyRingSpy).toHaveBeenCalledTimes(1);
    expect(simplifyRingSpy.mock.calls[0][1]).toBeCloseTo(2 / 1, 10);

    simplifyRingSpy.mockClear();
    runAt(4);
    expect(simplifyRingSpy).toHaveBeenCalledTimes(1);
    expect(simplifyRingSpy.mock.calls[0][1]).toBeCloseTo(2 / 4, 10);
  });
});
