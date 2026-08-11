// Draw-a-hole gesture (plan item 4): "Mark as hole"/"Remove hole" are
// gated on real geometry (findHoleHost/Measure.holes), so this renders
// through MeasureOverlay — which owns the ctxMenu open/close state and
// feeds MeasureCtxMenu the same `measures` the store holds — rather than
// unit-testing MeasureCtxMenu's props in isolation. The containment gate
// is the behavior under test, not the component's markup.

import { fireEvent, render } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";

import { fitView } from "../../lib/geometry";
import { useViewer, type Measure } from "../../store/viewer";
import MeasureOverlay from "./MeasureOverlay";

beforeAll(() => {
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
});

const IMG = { w: 100, h: 100 };
const VP = { w: 400, h: 400 };

// Fills the whole image — any ring strictly inside [0,1]x[0,1] is contained.
const OUTER: Measure["pts"] = [
  { x: 0, y: 0 },
  { x: 1, y: 0 },
  { x: 1, y: 1 },
  { x: 0, y: 1 },
];
const INNER: Measure["pts"] = [
  { x: 0.4, y: 0.4 },
  { x: 0.6, y: 0.4 },
  { x: 0.6, y: 0.6 },
  { x: 0.4, y: 0.6 },
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
  });

describe("MeasureCtxMenu — draw a hole (plan item 4)", () => {
  it('offers "Mark as hole" for a ring fully contained by another region', () => {
    const host: Measure = { id: "host", kind: "polygon", pts: OUTER };
    const ring: Measure = { id: "ring", kind: "polygon", pts: INNER };
    seed([host, ring]);
    const { container, getByText } = renderOverlay();
    const shapes = container.querySelectorAll("polygon");
    expect(shapes).toHaveLength(2);
    fireEvent.contextMenu(shapes[1]); // the ring, drawn second
    expect(getByText("Mark as hole")).toBeTruthy();
  });

  it('does not offer "Mark as hole" when nothing contains the ring (handles the no-host case)', () => {
    const a: Measure = {
      id: "a",
      kind: "polygon",
      pts: [
        { x: 0, y: 0 },
        { x: 0.3, y: 0 },
        { x: 0.3, y: 0.3 },
        { x: 0, y: 0.3 },
      ],
    };
    const b: Measure = {
      id: "b",
      kind: "polygon",
      pts: [
        { x: 0.7, y: 0.7 },
        { x: 1, y: 0.7 },
        { x: 1, y: 1 },
        { x: 0.7, y: 1 },
      ],
    };
    seed([a, b]); // disjoint — neither contains the other
    const { container, queryByText } = renderOverlay();
    const shapes = container.querySelectorAll("polygon");
    fireEvent.contextMenu(shapes[0]);
    expect(queryByText("Mark as hole")).toBeNull();
  });

  it('clicking "Mark as hole" moves the ring into the host and closes the menu', () => {
    const host: Measure = { id: "host", kind: "polygon", pts: OUTER };
    const ring: Measure = { id: "ring", kind: "polygon", pts: INNER };
    seed([host, ring]);
    const { container, getByText, queryByText } = renderOverlay();
    fireEvent.contextMenu(container.querySelectorAll("polygon")[1]);
    fireEvent.click(getByText("Mark as hole"));
    const measures = useViewer.getState().measures["img1"];
    expect(measures).toHaveLength(1);
    expect(measures[0].holes).toEqual([INNER]);
    expect(queryByText("Mark as hole")).toBeNull(); // menu closed
  });

  it('a region with a hole offers "Remove hole 1", which restores it as its own measure', () => {
    const host: Measure = { id: "host", kind: "polygon", pts: OUTER, holes: [INNER] };
    seed([host]);
    const { container, getByText } = renderOverlay();
    // a holed shape renders as an evenodd <path>, not a plain <polygon>
    const shape = container.querySelector("path");
    expect(shape).toBeTruthy();
    fireEvent.contextMenu(shape!);
    expect(getByText("Remove hole 1")).toBeTruthy();
    fireEvent.click(getByText("Remove hole 1"));
    const measures = useViewer.getState().measures["img1"];
    expect(measures).toHaveLength(2);
    expect(measures.find((m) => m.id === "host")!.holes).toEqual([]);
  });
});
