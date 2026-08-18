// Lasso-editing plan, item D — vertex delete (step 2) and alt+edge-drag
// insert (step 3), plus the Convention-6 regression pin that plain body
// drag still translates. Geometry is chosen so the screen<->image
// transform is exact (fitView on a 100x100 image into a 400x400 viewport
// gives z=4, so screen = 4 * image-px = 400 * normalized), which lets
// every assertion below use exact (not just approximate) coordinates.

import { fireEvent, render } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it } from "vitest";

import { fitView } from "../../lib/geometry";
import { useViewer, type Measure } from "../../store/viewer";
import MeasureOverlay from "./MeasureOverlay";

beforeAll(() => {
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
});

const IMG = { w: 100, h: 100 };
const VP = { w: 400, h: 400 };

// normalized 0.2-0.8 square -> screen (80,80)-(320,80)-(320,320)-(80,320)
const SQUARE: Measure["pts"] = [
  { x: 0.2, y: 0.2 },
  { x: 0.8, y: 0.2 },
  { x: 0.8, y: 0.8 },
  { x: 0.2, y: 0.8 },
];

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
  });

describe("MeasureOverlay vertex delete (item D step 2)", () => {
  beforeEach(() => seed([{ id: "m1", kind: "polygon", pts: SQUARE }]));

  it('offers "Delete vertex" for a right-clicked vertex of a 4-vertex polygon', () => {
    const { container, getByText } = renderOverlay();
    const handles = container.querySelectorAll("svg > g > g");
    expect(handles).toHaveLength(4);
    fireEvent.contextMenu(handles[0]);
    expect(getByText("Delete vertex")).toBeTruthy();
  });

  it("removes exactly the right-clicked vertex, going through updateMeasure (undoable)", () => {
    const { container, getByText } = renderOverlay();
    const handles = container.querySelectorAll("svg > g > g");
    fireEvent.contextMenu(handles[2]); // vertex 2 = {0.8, 0.8}
    fireEvent.click(getByText("Delete vertex"));
    const m = useViewer.getState().measures["img1"][0];
    expect(m.pts).toEqual([
      { x: 0.2, y: 0.2 },
      { x: 0.8, y: 0.2 },
      { x: 0.2, y: 0.8 },
    ]);
  });

  it("undo restores the pre-delete ring exactly", () => {
    const { container, getByText } = renderOverlay();
    const handles = container.querySelectorAll("svg > g > g");
    fireEvent.contextMenu(handles[1]);
    fireEvent.click(getByText("Delete vertex"));
    expect(useViewer.getState().measures["img1"][0].pts).toHaveLength(3);
    const entry = useViewer.getState().undo();
    expect(entry?.t).toBe("measure-move");
    expect(useViewer.getState().measures["img1"][0].pts).toEqual(SQUARE);
  });

  it("refreshes the on-screen area label after deletion (Convention 1)", () => {
    const { container, getByText } = renderOverlay();
    // 60x60 image-px square (0.2-0.8 of a 100x100 image) = 3600 px^2 before
    const before = [...container.querySelectorAll("text")].find((t) =>
      t.textContent?.includes("px²"),
    );
    expect(before?.textContent).toBe("3600 px²");
    const handles = container.querySelectorAll("svg > g > g");
    fireEvent.contextMenu(handles[0]); // drop {0.2,0.2} -> a right triangle
    fireEvent.click(getByText("Delete vertex"));
    // remaining triangle (0.8,0.2)-(0.8,0.8)-(0.2,0.8): half the square, 1800 px^2
    const after = [...container.querySelectorAll("text")].find((t) =>
      t.textContent?.includes("px²"),
    );
    expect(after?.textContent).toBe("1800 px²");
  });

  it("is absent at exactly 3 vertices — a polygon must stay a polygon", () => {
    seed([
      {
        id: "m1",
        kind: "polygon",
        pts: [SQUARE[0], SQUARE[1], SQUARE[2]],
      },
    ]);
    const { container, queryByText } = renderOverlay();
    const handles = container.querySelectorAll("svg > g > g");
    expect(handles).toHaveLength(3);
    fireEvent.contextMenu(handles[0]);
    expect(queryByText("Delete vertex")).toBeNull();
  });

  it("is absent for a kind without an editable vertex list, even with >3 points (a polyline)", () => {
    // 4 points, same length as SQUARE, isolates the KIND gate from the
    // >3-vertex gate — a mutant that dropped the kind check but kept the
    // length check would still pass a shorter/2-point fixture here.
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
    const handles = container.querySelectorAll("svg > g > g");
    expect(handles).toHaveLength(4);
    fireEvent.contextMenu(handles[0]);
    expect(queryByText("Delete vertex")).toBeNull();
  });
});

describe("MeasureOverlay alt+edge-drag vertex insert (item D step 3)", () => {
  beforeEach(() => seed([{ id: "m1", kind: "polygon", pts: SQUARE }]));

  it("carries the discoverability hint on the body path", () => {
    const { container } = renderOverlay();
    const polygon = container.querySelector("polygon")!;
    expect(polygon.getAttribute("title")).toBe(
      "alt-drag an edge to add a point",
    );
  });

  it("inserts a vertex at the grab point projected onto the segment, and drags it in the same gesture", () => {
    const { container } = renderOverlay();
    const polygon = container.querySelector("polygon")!;
    // top edge screen (80,80)-(320,80); grab its midpoint (200,80), which
    // is already ON the segment, so the projected point equals the grab
    // point exactly -> normalized (0.5, 0.2), inserted between vertex 0
    // and vertex 1.
    fireEvent.pointerDown(polygon, {
      clientX: 200,
      clientY: 80,
      altKey: true,
      pointerId: 1,
    });
    let m = useViewer.getState().measures["img1"][0];
    expect(m.pts).toEqual([
      { x: 0.2, y: 0.2 },
      { x: 0.5, y: 0.2 },
      { x: 0.8, y: 0.2 },
      { x: 0.8, y: 0.8 },
      { x: 0.2, y: 0.8 },
    ]);
    // same gesture continues the drag on the inserted vertex (index 1)
    fireEvent.pointerMove(polygon, { clientX: 200, clientY: 40, pointerId: 1 });
    m = useViewer.getState().measures["img1"][0];
    expect(m.pts[1]).toEqual({ x: 0.5, y: 0.1 });
    expect(m.pts).toHaveLength(5); // only the dragged vertex moved
    fireEvent.pointerUp(polygon, { pointerId: 1 });
  });

  it("collapses insert + drag into ONE undo step (undo restores the pre-insert ring)", () => {
    const { container } = renderOverlay();
    const polygon = container.querySelector("polygon")!;
    fireEvent.pointerDown(polygon, {
      clientX: 200,
      clientY: 80,
      altKey: true,
      pointerId: 1,
    });
    fireEvent.pointerMove(polygon, { clientX: 240, clientY: 60, pointerId: 1 });
    fireEvent.pointerUp(polygon, { pointerId: 1 });
    expect(useViewer.getState().measures["img1"][0].pts).toHaveLength(5);
    // exactly one undo entry for the whole gesture — not a separate one for
    // the insert plus another for the drag
    expect(useViewer.getState().undoStack).toHaveLength(1);
    const entry = useViewer.getState().undo();
    expect(entry?.t).toBe("measure-move");
    expect(useViewer.getState().measures["img1"][0].pts).toEqual(SQUARE);
  });

  it("plain (non-alt) drag on the body still TRANSLATES — Convention 6 regression pin", () => {
    const { container } = renderOverlay();
    const polygon = container.querySelector("polygon")!;
    fireEvent.pointerDown(polygon, {
      clientX: 150,
      clientY: 150,
      pointerId: 1,
    }); // no altKey
    fireEvent.pointerMove(polygon, {
      clientX: 200,
      clientY: 150,
      pointerId: 1,
    }); // +50 screen px -> +0.125 normalized (dx = 50 / (z=4 * img.w=100))
    const m = useViewer.getState().measures["img1"][0];
    expect(m.pts).toHaveLength(4); // no vertex inserted
    for (let i = 0; i < 4; i++) {
      expect(m.pts[i].x).toBeCloseTo(SQUARE[i].x + 0.125, 10);
      expect(m.pts[i].y).toBeCloseTo(SQUARE[i].y, 10);
    }
    fireEvent.pointerUp(polygon, { pointerId: 1 });
  });

  it("alt+drag on a non-closed-ring kind's body is a no-op for insert (kind gate) — box still just translates", () => {
    seed([
      {
        id: "b1",
        kind: "box",
        pts: [
          { x: 0.2, y: 0.2 },
          { x: 0.8, y: 0.8 },
        ],
      },
    ]);
    const { container } = renderOverlay();
    // index 0 is the transparent fat HIT twin (select-only); index 1 is the
    // box's own visual body, which carries the drag-starter onPointerDown.
    const rect = container.querySelectorAll("rect")[1];
    fireEvent.pointerDown(rect, {
      clientX: 150,
      clientY: 150,
      altKey: true,
      pointerId: 1,
    });
    fireEvent.pointerMove(rect, { clientX: 200, clientY: 150, pointerId: 1 });
    const m = useViewer.getState().measures["img1"][0];
    expect(m.pts).toHaveLength(2); // still a 2-corner box, nothing inserted
    expect(m.pts[0].x).toBeCloseTo(0.325, 10);
    fireEvent.pointerUp(rect, { pointerId: 1 });
  });
});
