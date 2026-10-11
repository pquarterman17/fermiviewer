import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import EdsSpectrumZoomBar from "./SpectrumZoomBar";

describe("EdsSpectrumZoomBar", () => {
  it("offers fitted signal and complete acquired views explicitly", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <EdsSpectrumZoomBar
        range={[0, 10]}
        bounds={[-0.5, 40]}
        minSpan={0.6}
        unit="keV"
        usefulRange={[0, 12]}
        onChange={onChange}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Fit signal" }));
    expect(onChange).toHaveBeenLastCalledWith([0, 12]);
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(onChange).toHaveBeenLastCalledWith(null);

    rerender(
      <EdsSpectrumZoomBar
        range={null}
        bounds={[0, 10]}
        minSpan={0.6}
        unit="keV"
        usefulRange={null}
        onChange={onChange}
      />,
    );
    expect(screen.getByRole("button", { name: "Fit signal" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reset" })).toBeDisabled();
  });
});
