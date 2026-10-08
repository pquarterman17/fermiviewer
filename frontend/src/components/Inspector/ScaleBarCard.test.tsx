// Scale Bar card length field: out-of-range lengths are refused with
// feedback instead of being stored (1e9 nm used to make a 33M-px bar and
// re-unit the field under the user) or silently ignored (0, -5).

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import type { ImageMeta } from "../../lib/api";
import { useViewer } from "../../store/viewer";
import ScaleBarCard from "./ScaleBarCard";

const img = {
  id: "img",
  name: "a.dm4",
  kind: "image",
  shape: [200, 300], // 300 px wide × 1 nm/px → 300 nm field of view
  dtype: "float32",
  pixel_size: 1,
  pixel_unit: "nm",
  value_unit: "",
  n_channels: null,
  energy_first: null,
  energy_last: null,
  energy_units: "",
  stage_tilt_deg: null,
  meta: {},
} as unknown as ImageMeta;

beforeEach(() => {
  useViewer.setState({
    images: { img },
    order: ["img"],
    activeId: "img",
    scaleBars: {},
  });
});

const lengthField = () => screen.getByPlaceholderText("auto");
const stored = () => useViewer.getState().scaleBars.img?.lengthPhys ?? null;

describe("ScaleBarCard length bounds", () => {
  it("refuses a length longer than the image and keeps the typed unit", () => {
    render(<ScaleBarCard />);
    fireEvent.click(screen.getByText("Scale Bar")); // expand the card
    fireEvent.change(lengthField(), { target: { value: "1e9" } });
    expect(screen.getByRole("alert").textContent).toMatch(/at most the image width \(300 nm\)/);
    expect(stored()).toBeNull();
    expect((lengthField() as HTMLInputElement).value).toBe("1e9");
  });

  it.each(["0", "-5"])("explains why %s is refused", (v) => {
    render(<ScaleBarCard />);
    fireEvent.click(screen.getByText("Scale Bar"));
    fireEvent.change(lengthField(), { target: { value: v } });
    expect(screen.getByRole("alert").textContent).toMatch(/greater than 0/);
    expect(stored()).toBeNull();
  });

  it("stores a valid length without re-formatting the field mid-typing", () => {
    render(<ScaleBarCard />);
    fireEvent.click(screen.getByText("Scale Bar"));
    fireEvent.change(lengthField(), { target: { value: "50" } });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(stored()).toBe(50);
    expect((lengthField() as HTMLInputElement).value).toBe("50");
  });
});
