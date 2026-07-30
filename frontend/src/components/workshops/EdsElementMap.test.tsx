import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { EdsElementMapResult } from "../../lib/api";
import EdsElementMap from "./EdsElementMap";

const result: EdsElementMapResult = {
  map: [[0, 1], [2, 100]],
  shape: [2, 2],
  e_lo: 6.315,
  e_hi: 6.485,
  bg: "linear",
  total_counts: 103,
  map_meta: null,
};

beforeEach(() => {
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
    createImageData: (width: number, height: number) => ({
      data: new Uint8ClampedArray(width * height * 4),
      width,
      height,
      colorSpace: "srgb",
    }),
    putImageData: vi.fn(),
  } as unknown as CanvasRenderingContext2D);
});

describe("EdsElementMap", () => {
  it("shows calibrated display controls and preserves scientific range context", () => {
    render(
      <EdsElementMap
        result={result}
        element="Fe"
        busy={false}
        libraryBusy={false}
        compositeBusy={false}
        canAddToComposite
        onAddToLibrary={() => {}}
        onAddToComposite={() => {}}
      />,
    );

    expect(screen.getByRole("region", { name: "Element map" })).toBeVisible();
    // A named element defaults to its own colour tint, so the single-element
    // map matches the colour it wears in the composite and on the spectrum.
    expect(screen.getByLabelText("Colormap")).toHaveValue("element");
    expect(screen.getByLabelText("Contrast")).toHaveValue("1-99");
    expect(screen.getByText(/Data range 0–100/)).toBeVisible();
    expect(screen.getByText(/negative pixels are retained/)).toBeVisible();
  });

  it("passes the selected colormap when registering the map", () => {
    const onAddToLibrary = vi.fn();
    render(
      <EdsElementMap
        result={result}
        element="Fe"
        busy={false}
        libraryBusy={false}
        compositeBusy={false}
        canAddToComposite
        onAddToLibrary={onAddToLibrary}
      />,
    );

    fireEvent.change(screen.getByLabelText("Colormap"), {
      target: { value: "inferno" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add to library" }));
    expect(onAddToLibrary).toHaveBeenCalledWith("inferno");
  });
});
