// Lasso-editing plan, item C — retroactive "Simplify outline" context-menu
// action. Renders through MeasureOverlay (same idiom as
// MeasureOverlay.vertexEdit.test.tsx) rather than unit-testing
// MeasureCtxMenu's props in isolation, since the behaviour under test is
// the wiring: menu -> simplifyRing -> updateMeasure/pushUndo -> the
// on-screen label (a pure function of pts, Convention 1). Every `it` below
// was mutation-verified: broken against a deliberately wrong
// implementation (RED), then restored (GREEN); the mutation tried is
// noted per test.

import { fireEvent, render } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { fitView, polygonStats } from "../../lib/geometry";
import { simplifyRing } from "../../lib/simplifyRing";
import { useViewer, type Measure } from "../../store/viewer";
import { fmt } from "./measureGlyphs";
import MeasureOverlay from "./MeasureOverlay";

// Wraps the REAL implementation (via importOriginal) so every test still
// exercises genuine Douglas-Peucker behaviour; only the epsilon-spy test
// inspects call args, everyone else gets identical results to the
// unmocked module.
vi.mock("../../lib/simplifyRing", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("../../lib/simplifyRing")>();
  return { ...actual, simplifyRing: vi.fn(actual.simplifyRing) };
});

beforeAll(() => {
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
});

const IMG = { w: 100, h: 100 };
const VP = { w: 400, h: 400 }; // fitView -> z = 4 (exact, see vertexEdit test)

const renderOverlay = () =>
  render(
    <MeasureOverlay
      imageId="img1"
      pixelSize={null}
      pixelUnit="px"
      view={fitView(IMG, VP)}
      img={IMG}
      vp={VP}
      pending={null}
    />,
  );

const seed = (measures: Measure[]) =>
  useViewer.setState({
    measures: { img1: measures },
    selectedMeasure: null,
    selectedMulti: [],
    undoStack: [],
    redoStack: [],
    status: "ready",
  });

/** Dense circle, NORMALIZED [0,1] coords (a fraction of the 100x100 IMG),
 *  radius `r` in image px, n points evenly spaced by angle — same shape
 *  family as simplifyRing.test.ts's denseCircle, just pre-divided by the
 *  image size to match the store's normalized-pts convention. */
function denseCircleNorm(r: number, n: number): Measure["pts"] {
  const pts: Measure["pts"] = [];
  for (let k = 0; k < n; k++) {
    const theta = (2 * Math.PI * k) / n;
    pts.push({
      x: 0.5 + (r * Math.cos(theta)) / IMG.w,
      y: 0.5 + (r * Math.sin(theta)) / IMG.h,
    });
  }
  return pts;
}

// A well-separated, already-minimal pentagon (image px roughly 10-95):
// every vertex deviates from its neighbours' chord by tens of image px —
// far more than any realistic screen-simplify epsilon — so simplifyRing
// removes nothing (hand-verified: farthest pair (P0,P2), both halves keep
// every point at eps=0.5). Also >3 vertices, so it stays a valid fixture
// for the "menu item present" pins.
const SPARSE_PENTAGON: Measure["pts"] = [
  { x: 0.1, y: 0.1 },
  { x: 0.9, y: 0.1 },
  { x: 0.9, y: 0.9 },
  { x: 0.5, y: 0.95 },
  { x: 0.1, y: 0.9 },
];

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
});

const rightClickShape = (container: HTMLElement) =>
  fireEvent.contextMenu(container.querySelector("polygon")!);

describe("MeasureCtxMenu — Simplify outline (lasso-editing plan, item C)", () => {
  it("offers Simplify outline for a polygon with more than 3 vertices", () => {
    seed([{ id: "m1", kind: "polygon", pts: SPARSE_PENTAGON }]);
    const { container, getByText } = renderOverlay();
    rightClickShape(container);
    expect(getByText("Simplify outline")).toBeTruthy();
  });

  it("offers Simplify outline for a lasso with more than 3 vertices", () => {
    seed([{ id: "m1", kind: "lasso", pts: SPARSE_PENTAGON }]);
    const { container, getByText } = renderOverlay();
    rightClickShape(container);
    expect(getByText("Simplify outline")).toBeTruthy();
  });

  it("is hidden at exactly 3 vertices — nothing left to simplify", () => {
    // Mutation tried: change the visibility gate from `pts.length > 3` to
    // `pts.length >= 3`, so a bare triangle offers an action that can
    // never do anything (simplifyRing never drops a ring below 3
    // vertices) -> RED (button present when it should be absent).
    // Restoring `> 3` fixes it, GREEN.
    seed([
      {
        id: "m1",
        kind: "polygon",
        pts: [SPARSE_PENTAGON[0], SPARSE_PENTAGON[1], SPARSE_PENTAGON[2]],
      },
    ]);
    const { container, queryByText } = renderOverlay();
    rightClickShape(container);
    expect(queryByText("Simplify outline")).toBeNull();
  });

  it("is absent for kinds without an editable outline, even with >3 points (kind gate)", () => {
    // Mutation tried: drop the kind check from `canSimplify` (keep only
    // the length check) -> a 4-point polyline, which has no closed
    // "outline" concept at all, offers "Simplify outline", RED. Restoring
    // the `kind === "polygon" || kind === "lasso"` check fixes it, GREEN.
    seed([
      {
        id: "p1",
        kind: "polyline",
        pts: [
          { x: 0.1, y: 0.1 },
          { x: 0.4, y: 0.1 },
          { x: 0.4, y: 0.4 },
          { x: 0.7, y: 0.7 },
        ],
      },
    ]);
    const { container, queryByText } = renderOverlay();
    fireEvent.contextMenu(container.querySelector("polyline")!);
    expect(queryByText("Simplify outline")).toBeNull();
  });

  it("is absent for line (distance)/box/ellipse", () => {
    for (const m of [
      {
        id: "d1",
        kind: "distance" as const,
        pts: [
          { x: 0.1, y: 0.1 },
          { x: 0.8, y: 0.8 },
        ],
      },
      {
        id: "b1",
        kind: "box" as const,
        pts: [
          { x: 0.1, y: 0.1 },
          { x: 0.8, y: 0.8 },
        ],
      },
      {
        id: "e1",
        kind: "ellipse" as const,
        pts: [
          { x: 0.1, y: 0.1 },
          { x: 0.8, y: 0.8 },
        ],
      },
    ]) {
      seed([m]);
      const { container, queryByText, unmount } = renderOverlay();
      const shape = container.querySelector(
        m.kind === "distance" ? "line" : m.kind === "box" ? "rect" : "ellipse",
      )!;
      fireEvent.contextMenu(shape);
      expect(queryByText("Simplify outline")).toBeNull();
      unmount();
    }
  });

  it("reduces vertex count on a dense ring and updates the on-screen area label", () => {
    // Mutation tried: swap `updateMeasure(imageId, at.mid, after)` for a
    // no-op inside the `if (afterPx.length < before.length)` branch (the
    // action recognizes the ring COULD be simplified but never applies
    // it) -> stored pts count stays at 400 and the label stays at its
    // pre-click value, RED (both assertions below fail). Restoring the
    // updateMeasure call fixes it, GREEN.
    localStorage.setItem("fv_prefs", JSON.stringify({ lassoCloseSimplifyPx: 4 }));
    const ring = denseCircleNorm(40, 400);
    seed([{ id: "m1", kind: "polygon", pts: ring }]);
    const { container, getByText } = renderOverlay();

    const findAreaLabel = () =>
      [...container.querySelectorAll("text")].find((t) =>
        t.textContent?.includes("px²"),
      );

    const beforePx = ring.map((p) => ({ x: p.x * IMG.w, y: p.y * IMG.h }));
    const beforeArea = polygonStats(beforePx).areaPx2;
    expect(findAreaLabel()?.textContent).toBe(`${fmt(beforeArea)} px²`);

    rightClickShape(container);
    fireEvent.click(getByText("Simplify outline"));

    const m = useViewer.getState().measures["img1"][0];
    expect(m.pts.length).toBeLessThan(ring.length);

    // epsilon = lassoCloseSimplifyPx / view.z = 4 / 4 = 1 image px — the exact
    // same conversion the component performs, so the expected result is
    // computed via the identical production simplifyRing + polygonStats
    // + fmt path rather than a hand-derived magic number.
    const expectedAfterPx = simplifyRing(beforePx, 1);
    expect(m.pts.length).toBe(expectedAfterPx.length);

    const expectedAfterArea = polygonStats(expectedAfterPx).areaPx2;
    const afterLabel = findAreaLabel();
    expect(afterLabel?.textContent).toBe(`${fmt(expectedAfterArea)} px²`);
    expect(afterLabel?.textContent).not.toBe(`${fmt(beforeArea)} px²`);
  });

  it("undo restores the exact pre-simplify pts (deep-equal)", () => {
    // Mutation tried: change pushUndo's `before` field from `before` (the
    // pre-simplify snapshot) to `after` (the just-applied result), so
    // undo restores the ALREADY-simplified ring instead of the original
    // -> undo() is a no-op in effect, RED (pts stay at the simplified
    // count/shape instead of reverting to the dense ring). Restoring
    // `before` fixes it, GREEN.
    localStorage.setItem("fv_prefs", JSON.stringify({ lassoCloseSimplifyPx: 4 }));
    const ring = denseCircleNorm(40, 400);
    seed([{ id: "m1", kind: "lasso", pts: ring }]);
    const { container, getByText } = renderOverlay();

    rightClickShape(container);
    fireEvent.click(getByText("Simplify outline"));
    expect(useViewer.getState().measures["img1"][0].pts.length).toBeLessThan(
      ring.length,
    );

    const entry = useViewer.getState().undo();
    expect(entry?.t).toBe("measure-move");
    expect(useViewer.getState().measures["img1"][0].pts).toEqual(ring);
  });

  it("no-op case: an already-simplified ring is left unchanged, no undo entry, status message shown", () => {
    // Mutation tried: remove the `if (afterPx.length < before.length)`
    // guard entirely, always calling updateMeasure/pushUndo with
    // whatever simplifyRing returns -> even though vertex COUNT is
    // unchanged, simplifyRing's rotated/re-anchored output (a different
    // array, walked from the farthest-pair anchor rather than the
    // original start) replaces the stored pts and an undo entry is
    // pushed for a functional no-op, RED (pts reference changes, undoStack
    // grows, no status message). Restoring the guard fixes it, GREEN.
    seed([{ id: "m1", kind: "polygon", pts: SPARSE_PENTAGON }]);
    const { container, getByText } = renderOverlay();

    rightClickShape(container);
    fireEvent.click(getByText("Simplify outline"));

    const m = useViewer.getState().measures["img1"][0];
    expect(m.pts).toBe(SPARSE_PENTAGON); // same reference — never touched
    expect(m.pts).toEqual(SPARSE_PENTAGON);
    expect(useViewer.getState().undoStack).toHaveLength(0);
    expect(useViewer.getState().status).toBe(
      "outline already simplified — no vertices removed",
    );
  });

  it("epsilon passed to simplifyRing is prefs.lassoCloseSimplifyPx / view.z (Convention 3)", () => {
    // Mutation tried: swap the epsilon expression from
    // `loadPrefs().lassoCloseSimplifyPx / view.z` to
    // `loadPrefs().lassoCloseSimplifyPx * view.z` (division -> multiplication)
    // -> at lassoCloseSimplifyPx=6, z=4 the spy sees 24 instead of 1.5, RED.
    // Restoring the division fixes it, GREEN.
    localStorage.setItem("fv_prefs", JSON.stringify({ lassoCloseSimplifyPx: 6 }));
    seed([{ id: "m1", kind: "polygon", pts: SPARSE_PENTAGON }]);
    const { container, getByText } = renderOverlay();

    rightClickShape(container);
    fireEvent.click(getByText("Simplify outline"));

    expect(simplifyRing).toHaveBeenCalledTimes(1);
    const [, epsilon] = vi.mocked(simplifyRing).mock.calls[0];
    expect(epsilon).toBe(6 / 4); // lassoCloseSimplifyPx / view.z, z=4 at this fitView
  });
});
