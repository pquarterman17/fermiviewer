// Regression (email 2026-07-02 "can't delete all types of measurement"):
// a text annotation must be SELECTABLE by clicking its label. The label is
// a text annotation's ONLY hit target — no line, shape, or fat hit layer —
// so if the label's pointerdown doesn't select, Del falls through to
// closing the whole image instead of deleting the annotation.

import { fireEvent, render } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it } from "vitest";

import { fitView } from "../../lib/geometry";
import { useViewer, type Measure } from "../../store/viewer";
import MeasureOverlay from "./MeasureOverlay";

// jsdom has no pointer capture; the handler calls it after selecting.
beforeAll(() => {
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
});

const IMG = { w: 100, h: 100 };
const VP = { w: 400, h: 400 };

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

beforeEach(() => {
  const text: Measure = {
    id: "t1",
    kind: "text",
    pts: [{ x: 0.5, y: 0.5 }],
    text: "hello",
  };
  useViewer.setState({
    measures: { img1: [text] },
    selectedMeasure: null,
    selectedMulti: [],
  });
});

describe("MeasureOverlay text-annotation selection", () => {
  it("selects the annotation when its label is clicked", () => {
    expect(useViewer.getState().selectedMeasure).toBeNull();
    const { container } = renderOverlay();
    const label = [...container.querySelectorAll("text")].find(
      (t) => t.textContent === "hello",
    );
    expect(label).toBeTruthy();
    fireEvent.pointerDown(label!);
    // now Del (App.tsx) can target the annotation instead of the image
    expect(useViewer.getState().selectedMeasure).toBe("t1");
  });

  it("selects the annotation on right-click (context menu)", () => {
    const { container } = renderOverlay();
    const label = [...container.querySelectorAll("text")].find(
      (t) => t.textContent === "hello",
    );
    fireEvent.contextMenu(label!);
    expect(useViewer.getState().selectedMeasure).toBe("t1");
  });
});
