import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import type { ImageMeta } from "../../lib/api";
import { useBrowseScale } from "../../store/browseScale";
import { useStageInfo } from "../../store/stage";
import { useViewer } from "../../store/viewer";
import ScaleLockChip from "./ScaleLockChip";

function image(overrides: Partial<ImageMeta> = {}): ImageMeta {
  return {
    id: "a",
    name: "a.tif",
    kind: "image",
    shape: [512, 512],
    dtype: "uint16",
    pixel_size: 3.4,
    pixel_unit: "nm",
    meta: {},
    ...overrides,
  } as ImageMeta;
}

const resetBrowseScale = () =>
  useBrowseScale.setState({ locked: false, scale: null });

beforeEach(() => {
  resetBrowseScale();
  useViewer.setState({ activeId: "a", order: ["a"], images: { a: image() } });
  // z = screen px per image px; pixelSize 3.4 nm/px → 3.4 / 2 = 1.7 nm/px
  useStageInfo.setState({ zoom: 2 });
});

describe("ScaleLockChip", () => {
  it("has an accessible name and exposes its pressed state, off by default", () => {
    render(<ScaleLockChip />);
    const btn = screen.getByRole("button", { name: "Lock physical scale" });
    expect(btn).toHaveAttribute("aria-pressed", "false");
  });

  it("shows the active image's current scale with its own unit, not a hardcoded µm", () => {
    render(<ScaleLockChip />);
    expect(screen.getByText("1.7 nm/px")).toBeVisible();
  });

  it("updates the readout when the active image (and its unit) changes", () => {
    const { rerender } = render(<ScaleLockChip />);
    expect(screen.getByText("1.7 nm/px")).toBeVisible();

    useViewer.setState({
      images: { a: image({ pixel_size: 1.76, pixel_unit: "µm" }) },
    });
    useStageInfo.setState({ zoom: 1 }); // 1.76 µm/px at z=1
    rerender(<ScaleLockChip />);
    expect(screen.getByText("1.76 µm/px")).toBeVisible();
  });

  it("toggling on then off leaves the current view unchanged (no visual jump)", () => {
    render(<ScaleLockChip />);
    const btn = screen.getByRole("button", { name: "Lock physical scale" });
    const before = screen.getByText("1.7 nm/px");
    expect(before).toBeVisible();

    fireEvent.click(btn); // enable — seeds from the CURRENT physical scale
    expect(btn).toHaveAttribute("aria-pressed", "true");
    expect(useBrowseScale.getState()).toMatchObject({ locked: true, scale: 1.7 });
    expect(screen.getByText("1.7 nm/px")).toBeVisible(); // unchanged readout

    fireEvent.click(btn); // disable
    expect(btn).toHaveAttribute("aria-pressed", "false");
    expect(useBrowseScale.getState()).toMatchObject({ locked: false, scale: null });
    expect(screen.getByText("1.7 nm/px")).toBeVisible(); // still unchanged
  });

  it("disables the toggle with a reason when the active image is uncalibrated", () => {
    useViewer.setState({
      images: { a: image({ pixel_size: null }) },
    });
    render(<ScaleLockChip />);
    const btn = screen.getByRole("button", { name: "Lock physical scale" });
    expect(btn).toBeDisabled();
    // disabled controls swallow pointer events — the tip must live on the
    // hoverable wrapper, mirroring FloatTools' side-by-side-compare pattern
    expect(btn).not.toHaveAttribute("data-tip");
    expect(btn.parentElement).toHaveAttribute("data-tip", "Constant scale lock");
    expect(btn.parentElement).toHaveAttribute("data-tip-detail");
    expect(screen.getByText("—")).toBeVisible();
  });

  it("clicking while uncalibrated does not enable the lock", () => {
    useViewer.setState({
      images: { a: image({ pixel_size: null }) },
    });
    render(<ScaleLockChip />);
    const btn = screen.getByRole("button", { name: "Lock physical scale" });
    fireEvent.click(btn);
    expect(useBrowseScale.getState().locked).toBe(false);
  });

  it("renders nothing when there is no active image", () => {
    useViewer.setState({ activeId: null });
    const { container } = render(<ScaleLockChip />);
    expect(container).toBeEmptyDOMElement();
  });
});
