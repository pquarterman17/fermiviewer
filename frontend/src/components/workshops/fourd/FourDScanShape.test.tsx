import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { FourDMeta } from "../../../lib/api";
import FourDScanShape from "./FourDScanShape";

const meta = (over: Partial<FourDMeta> = {}): FourDMeta => ({
  id: "4d-1",
  name: "scan.mib",
  is_fourd: true,
  source: "/data/scan.mib",
  scan_shape: [1, 12],
  det_shape: [4, 16],
  dtype: "uint8",
  scan_axes: [],
  det_axes: [],
  nav_available: true,
  n_frames: 12,
  scan_shape_from_file: false,
  scan_shape_options: [
    [4, 3],
    [3, 4],
    [6, 2],
    [1, 12],
  ],
  ...over,
});

const apply = () => screen.getByRole("button", { name: "Apply" });

describe("FourDScanShape", () => {
  it("does not offer to re-raster a file that records its own scan", () => {
    const { container } = render(
      <FourDScanShape
        meta={meta({ scan_shape_from_file: true, scan_shape_options: [] })}
        busy={false}
        onApply={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("seeds the fields from the shape the dataset currently claims", () => {
    render(<FourDScanShape meta={meta()} busy={false} onApply={vi.fn()} />);
    expect(screen.getByLabelText("Scan rows")).toHaveValue(1);
    expect(screen.getByLabelText("Scan columns")).toHaveValue(12);
    // ...which is the current shape, so there is nothing to apply yet.
    expect(apply()).toBeDisabled();
  });

  it("applies a shape whose product is the frame count", () => {
    const onApply = vi.fn();
    render(<FourDScanShape meta={meta()} busy={false} onApply={onApply} />);
    fireEvent.change(screen.getByLabelText("Scan rows"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Scan columns"), { target: { value: "4" } });
    expect(apply()).toBeEnabled();
    fireEvent.click(apply());
    expect(onApply).toHaveBeenCalledWith(3, 4);
  });

  it("refuses — and explains — a shape that is not the frame count", () => {
    const onApply = vi.fn();
    render(<FourDScanShape meta={meta()} busy={false} onApply={onApply} />);
    fireEvent.change(screen.getByLabelText("Scan rows"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Scan columns"), { target: { value: "3" } });
    expect(apply()).toBeDisabled();
    // The message names the constraint AND the product, so the user can see
    // which of the two numbers to change.
    expect(screen.getByText(/must multiply to 12 frames \(got 15\)/)).toBeInTheDocument();
    expect(onApply).not.toHaveBeenCalled();
  });

  it("refuses a zero or negative raster", () => {
    render(<FourDScanShape meta={meta()} busy={false} onApply={vi.fn()} />);
    for (const value of ["0", "-3", ""]) {
      fireEvent.change(screen.getByLabelText("Scan rows"), { target: { value } });
      expect(apply()).toBeDisabled();
    }
  });

  it("applies a suggested factorisation in one click", () => {
    const onApply = vi.fn();
    render(<FourDScanShape meta={meta()} busy={false} onApply={onApply} />);
    fireEvent.click(screen.getByRole("button", { name: "4×3" }));
    expect(onApply).toHaveBeenCalledWith(4, 3);
    // The typed fields follow the chip, so the two controls never disagree.
    expect(screen.getByLabelText("Scan rows")).toHaveValue(4);
    expect(screen.getByLabelText("Scan columns")).toHaveValue(3);
  });

  it("marks the suggestion that is already in effect", () => {
    render(
      <FourDScanShape
        meta={meta({ scan_shape: [4, 3] })}
        busy={false}
        onApply={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "4×3" }).className).toContain("active");
    expect(screen.getByRole("button", { name: "3×4" }).className).not.toContain("active");
  });

  it("re-seeds when the applied shape comes back changed", () => {
    const { rerender } = render(
      <FourDScanShape meta={meta()} busy={false} onApply={vi.fn()} />,
    );
    rerender(
      <FourDScanShape meta={meta({ scan_shape: [3, 4] })} busy={false} onApply={vi.fn()} />,
    );
    // A stale 1×12 left in the fields would read as "the reshape did not take".
    expect(screen.getByLabelText("Scan rows")).toHaveValue(3);
    expect(screen.getByLabelText("Scan columns")).toHaveValue(4);
  });

  it("locks every control while a reshape is in flight", () => {
    render(<FourDScanShape meta={meta()} busy onApply={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Scan rows"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Scan columns"), { target: { value: "4" } });
    expect(apply()).toBeDisabled();
    expect(screen.getByRole("button", { name: "4×3" })).toBeDisabled();
  });
});
