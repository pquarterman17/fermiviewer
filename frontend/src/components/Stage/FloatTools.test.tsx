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
    expect(screen.getByRole("button", { name: "Rotate 90° CCW" })).toBeVisible();

    const hand = screen.getByRole("button", { name: "Hand tool" });
    expect(hand).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(hand);
    expect(hand).toHaveAttribute("aria-pressed", "true");

    expect(screen.getByRole("button", { name: "Side-by-side compare" })).toBeDisabled();
  });

  it("gives the zoom controls useful names", () => {
    render(<ZoomChip onZoom={() => undefined} />);
    expect(screen.getByRole("button", { name: "Zoom out" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Zoom in" })).toBeVisible();
  });
});
