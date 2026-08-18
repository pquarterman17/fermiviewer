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

  it("carries the discoverability hint on the body path as a <title> CHILD element (dead SVG tooltip fix — a `title` ATTRIBUTE renders nothing in a browser; SVG needs a <title> element)", () => {
    const { container } = renderOverlay();
    const polygon = container.querySelector("polygon")!;
    const titleEl = polygon.querySelector("title");
    expect(titleEl?.textContent).toBe("alt-drag an edge to add a point");
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

  it("alt+drag from deep in the interior does NOT insert a vertex — falls through to plain translate (alt-drag-from-interior fix)", () => {
    // The 80-320 screen-px square's centroid is (200,200), ~120 screen px
    // from its nearest edge — far past the ~12px edge-grab gate, so a
    // down-point this deep inside must be REJECTED by tryEdgeInsertDrag and
    // fall through to the plain whole-body translate, not insert a vertex
    // at the (very distant) nearest-edge projection and then teleport it to
    // the pointer on the first move — the interior-alt-drag spike bug this
    // PR exists to kill.
    const { container } = renderOverlay();
    const polygon = container.querySelector("polygon")!;
    fireEvent.pointerDown(polygon, {
      clientX: 200,
      clientY: 200,
      altKey: true,
      pointerId: 1,
    });
    let m = useViewer.getState().measures["img1"][0];
    expect(m.pts).toHaveLength(4); // no vertex inserted
    expect(m.pts).toEqual(SQUARE); // untouched by pointerdown alone

    // same translate math as the Convention 6 regression pin above: +50
    // screen px -> +0.125 normalized (dx = 50 / (z=4 * img.w=100))
    fireEvent.pointerMove(polygon, {
      clientX: 250,
      clientY: 200,
      pointerId: 1,
    });
    m = useViewer.getState().measures["img1"][0];
    expect(m.pts).toHaveLength(4); // still no vertex inserted
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

describe("MeasureOverlay body-translate carries holes along (pre-existing bug, holes-detach fix)", () => {
  // Normalized 0.4-0.6 square, well inside SQUARE (0.2-0.8) — a marked
  // hole (Measure.holes), same normalized 0-1 convention as pts.
  const HOLE: Measure["pts"] = [
    { x: 0.4, y: 0.4 },
    { x: 0.6, y: 0.4 },
    { x: 0.6, y: 0.6 },
    { x: 0.4, y: 0.6 },
  ];

  beforeEach(() =>
    seed([{ id: "m1", kind: "polygon", pts: SQUARE, holes: [HOLE] }]),
  );

  it("body drag shifts hole vertices by the SAME delta as the body's own pts, and undo restores both", () => {
    const { container } = renderOverlay();
    // holes>0 makes ClosedShapeGlyph render a <path> (evenodd fill), not a
    // <polygon> — see closedShapeGlyph.tsx.
    const body = container.querySelector("path")!;
    fireEvent.pointerDown(body, { clientX: 150, clientY: 150, pointerId: 1 });
    // +50 screen px -> +0.125 normalized (dx = 50 / (z=4 * img.w=100)), same
    // translate math as the Convention 6 regression pin above
    fireEvent.pointerMove(body, { clientX: 200, clientY: 150, pointerId: 1 });

    let m = useViewer.getState().measures["img1"][0];
    for (let i = 0; i < 4; i++) {
      expect(m.pts[i].x).toBeCloseTo(SQUARE[i].x + 0.125, 10);
      expect(m.pts[i].y).toBeCloseTo(SQUARE[i].y, 10);
    }
    expect(m.holes).toBeDefined();
    for (let i = 0; i < 4; i++) {
      expect(m.holes![0][i].x).toBeCloseTo(HOLE[i].x + 0.125, 10);
      expect(m.holes![0][i].y).toBeCloseTo(HOLE[i].y, 10);
    }
    fireEvent.pointerUp(body, { pointerId: 1 });

    const entry = useViewer.getState().undo();
    expect(entry?.t).toBe("measure-move");
    m = useViewer.getState().measures["img1"][0];
    expect(m.pts).toEqual(SQUARE);
    expect(m.holes).toEqual([HOLE]);
  });
});

describe("MeasureOverlay handle glyph rendering", () => {
  it("polygon measure's rendered handles contain <circle> elements and NO EndpointGlyph bars", () => {
    seed([{ id: "m1", kind: "polygon", pts: SQUARE }]);
    const { container } = renderOverlay();
    const handleGroups = container.querySelectorAll("svg > g > g");
    expect(handleGroups).toHaveLength(4);

    // Each handle group should contain a circle
    handleGroups.forEach((group) => {
      const circles = group.querySelectorAll("circle");
      expect(circles.length).toBeGreaterThan(0); // at least the visible circle
      // Verify the visible circle (not the hit target) has the right properties
      const visibleCircle = circles[0];
      expect(visibleCircle.getAttribute("r")).toBe("3");
      expect(visibleCircle.getAttribute("fill")).toBe("var(--surface-0)");

      // No EndpointGlyph bar (which is a line element)
      const lines = group.querySelectorAll("line");
      expect(lines).toHaveLength(0);
    });
  });

  it("line measure still renders EndpointGlyph (regression pin)", () => {
    seed([
      {
        id: "m1",
        kind: "distance",
        pts: [
          { x: 0.2, y: 0.2 },
          { x: 0.8, y: 0.8 },
        ],
      },
    ]);
    const { container } = renderOverlay();
    const handleGroups = container.querySelectorAll("svg > g > g");
    expect(handleGroups).toHaveLength(2);

    // Each handle group should contain a line (the EndpointGlyph bar)
    handleGroups.forEach((group) => {
      const lines = group.querySelectorAll("line");
      expect(lines.length).toBeGreaterThan(0); // the bar glyph

      // No circles except the hit target (which is inside EndpointGlyph)
      const circles = group.querySelectorAll("circle");
      expect(circles.length).toBeGreaterThan(0); // the hit target from EndpointGlyph
    });
  });
});
