import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ImageMeta } from "../../lib/api";
import { useViewer } from "../../store/viewer";
import EdsWorkshop from "./EdsWorkshop";

vi.mock("./EdsSpectrumImage", () => ({
  default: () => <div>Explore surface</div>,
}));
vi.mock("./EdsMapsTab", () => ({
  default: () => <div>Maps surface</div>,
}));
vi.mock("./EdsModelFit", () => ({
  default: () => <div>Model-fit surface</div>,
}));

const cube: ImageMeta = {
  id: "cube",
  name: "cube.dm4",
  kind: "spectrum_image",
  shape: [8, 8, 128],
  dtype: "float32",
  pixel_size: 1,
  pixel_unit: "nm",
  value_unit: "",
  n_channels: 128,
  energy_first: 0,
  energy_last: 12.7,
  energy_units: "keV",
  stage_tilt_deg: null,
  meta: {},
};

beforeEach(() => {
  useViewer.setState({
    images: { cube },
    order: ["cube"],
    activeId: "cube",
  });
});

describe("EdsWorkshop workspace modes", () => {
  it("opens on Maps — the identify-then-map workflow, not a blank form", () => {
    render(<EdsWorkshop />);
    expect(screen.getByText("Maps surface")).toBeVisible();
    expect(screen.getByRole("tab", { name: "Maps" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("keeps routine exploration separate from advanced workflows", () => {
    render(<EdsWorkshop />);
    fireEvent.click(screen.getByRole("tab", { name: "Explore" }));
    expect(screen.getByText("Explore surface")).toBeVisible();

    fireEvent.click(screen.getByRole("tab", { name: "Quantify" }));
    expect(screen.getByRole("button", { name: "Quantify" })).toBeVisible();
    expect(screen.queryByText("Explore surface")).toBeNull();

    fireEvent.click(screen.getByRole("tab", { name: "Composite" }));
    expect(
      screen.getByText(/Add element maps from Explore/),
    ).toBeVisible();

    fireEvent.click(screen.getByRole("tab", { name: "Model fit" }));
    expect(screen.getByText("Model-fit surface")).toBeVisible();
  });
});
