import { act, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { useRegionPreviewStore } from "../../store/regionPreview";
import MaskPreviewOverlay, {
  MASK_PREVIEW_OPACITY,
  MASK_PREVIEW_RGB,
  maskPreviewBox,
  tintMatrix,
} from "./MaskPreviewOverlay";

const view = { z: 1, px: 0.5, py: 0.5 };
const size = { w: 100, h: 100 };
const HREF = "data:image/png;base64,AA==";

describe("maskPreviewBox", () => {
  it("covers the footprint of 1-based inclusive pixels, edge to edge", () => {
    // columns 20..23 span [19, 23] in the image frame; rows 10..12 span [9, 12]
    expect(maskPreviewBox([10, 20, 12, 23], view, size, size)).toEqual({
      x: 19, y: 9, width: 4, height: 3,
    });
  });

  it("scales with the zoom", () => {
    expect(maskPreviewBox([1, 1, 100, 100], { z: 2, px: 0.5, py: 0.5 }, size, size)).toEqual({
      x: -50, y: -50, width: 200, height: 200,
    });
  });
});

describe("MaskPreviewOverlay", () => {
  afterEach(() => {
    act(() => useRegionPreviewStore.setState({ mask: null }));
  });

  it("draws nothing without a mask, or with another image's mask", () => {
    const { container } = render(
      <MaskPreviewOverlay imageId="a" view={view} img={size} vp={size} />,
    );
    expect(container.querySelector("svg")).toBeNull();
    act(() => {
      useRegionPreviewStore.getState().showMask({
        imageId: "b", regionRef: "s/r", rect: [1, 1, 2, 2], href: HREF,
      });
    });
    expect(container.querySelector("svg")).toBeNull();
  });

  it("places the tinted PNG at the mask's box, pixel for pixel", () => {
    act(() => {
      useRegionPreviewStore.getState().showMask({
        imageId: "a", regionRef: "s/r", rect: [10, 20, 12, 23], href: HREF,
      });
    });
    const { container } = render(
      <MaskPreviewOverlay imageId="a" view={view} img={size} vp={size} />,
    );
    const image = container.querySelector("image")!;
    expect(image.getAttribute("href")).toBe(HREF);
    expect(image.getAttribute("x")).toBe("19");
    expect(image.getAttribute("y")).toBe("9");
    expect(image.getAttribute("width")).toBe("4");
    expect(image.getAttribute("height")).toBe("3");
    expect(image.getAttribute("preserveAspectRatio")).toBe("none");
    expect(image.getAttribute("filter")).toMatch(/^url\(#mask-tint-/);
    expect(container.querySelector("feColorMatrix")!.getAttribute("values")).toBe(
      tintMatrix(MASK_PREVIEW_RGB, MASK_PREVIEW_OPACITY),
    );
    expect(container.querySelector("svg")!.getAttribute("data-region-ref")).toBe("s/r");
  });
});
