import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import type { ImageMeta } from "../../lib/api";
import { useStageInfo } from "../../store/stage";
import { useViewer } from "../../store/viewer";
import { FloatTools, ZoomChip } from "./FloatTools";

const image = {
  id: "a",
  name: "a.tif",
  kind: "image",
  shape: [10, 10],
  dtype: "uint8",
  pixel_size: null,
  pixel_unit: "",
  meta: {},
} as ImageMeta;

beforeEach(() => {
  useViewer.setState({
    activeId: "a",
    order: ["a"],
    images: { a: image },
    measures: {},
    captureMode: "none",
    panTool: false,
  });
  useStageInfo.setState({ zoom: 1 });
});

describe("FloatTools accessibility", () => {
  it("names glyph-only controls and exposes toggle state", () => {
    render(<FloatTools />);
    expect(
      screen.getByRole("toolbar", { name: "Image and measurement tools" }),
    ).toBeVisible();
    const rotate = screen.getByRole("button", { name: "Rotate 90° CCW" });
    expect(rotate).toBeVisible();
    expect(rotate.querySelector("svg.fvd-icon")).not.toBeNull();

    const hand = screen.getByRole("button", { name: "Hand tool" });
    expect(hand).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(hand);
    expect(hand).toHaveAttribute("aria-pressed", "true");

    expect(screen.getByRole("button", { name: "Side-by-side compare" })).toBeDisabled();
  });

  it("gives the zoom controls useful names", () => {
    render(<ZoomChip onZoom={() => undefined} />);
    const out = screen.getByRole("button", { name: "Zoom out" });
    const inside = screen.getByRole("button", { name: "Zoom in" });
    expect(out.querySelector("svg.fvd-icon")).not.toBeNull();
    expect(inside.querySelector("svg.fvd-icon")).not.toBeNull();
  });

  it("every tipped toolbar button carries an explanatory detail", () => {
    // the old Record<string, string> lookup typed missing entries away — the
    // transform buttons shipped without details for months
    render(<FloatTools />);
    const tipped = screen
      .getAllByRole("button")
      .filter((b) => b.hasAttribute("data-tip"));
    expect(tipped.length).toBeGreaterThanOrEqual(16);
    for (const b of tipped) {
      expect(b).toHaveAttribute("data-tip-detail");
    }
  });

  it("moves the compare tip to a hoverable wrapper while disabled, with the why", () => {
    render(<FloatTools />); // default store: one image → compare unavailable
    const btn = screen.getByRole("button", { name: "Side-by-side compare" });
    expect(btn).toBeDisabled();
    // a disabled control swallows pointer events, so the tip must NOT live on
    // the button — the wrapper is what the browser lets the pointer reach
    expect(btn).not.toHaveAttribute("data-tip");
    expect(btn.parentElement).toHaveAttribute("data-tip", "Side-by-side compare");
    expect(btn.parentElement).toHaveAttribute(
      "data-tip-detail",
      "Open at least two images to compare side-by-side.",
    );
  });

  it("keeps the compare tip on the focusable button when enabled", () => {
    useViewer.setState({ order: ["a", "b"] });
    render(<FloatTools />);
    const btn = screen.getByRole("button", { name: "Side-by-side compare" });
    expect(btn).toBeEnabled();
    expect(btn).toHaveAttribute("data-tip", "Side-by-side compare");
    expect(btn).toHaveAttribute(
      "data-tip-detail",
      "Open loaded images in linked panes for visual comparison.",
    );
    expect(btn.parentElement).not.toHaveAttribute("data-tip");
  });
});
