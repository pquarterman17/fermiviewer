import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ImageMeta } from "../../lib/api";
import { useViewer } from "../../store/viewer";
import ElementalWorkshop from "./ElementalWorkshop";

vi.mock("../elemental/MapsTab", () => ({
  default: () => <div>Maps surface</div>,
}));
vi.mock("./EdsSpectrumImage", () => ({
  default: () => <div>EDS explore surface</div>,
}));
vi.mock("./EdsModelFit", () => ({
  default: () => <div>EDS model-fit surface</div>,
}));
vi.mock("./EdsQuantifyPanel", () => ({
  default: () => <div>EDS quantify surface</div>,
}));
vi.mock("./EelsWorkshop", () => ({
  default: ({ tab }: { tab: string }) => <div>EELS surface: {tab}</div>,
}));

function cube(overrides: Partial<ImageMeta> = {}): ImageMeta {
  return {
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
    ...overrides,
  } as ImageMeta;
}

function open(meta: ImageMeta) {
  useViewer.setState({ images: { [meta.id]: meta }, order: [meta.id], activeId: meta.id });
}

beforeEach(() => {
  localStorage.clear();
  open(cube());
});

describe("ElementalWorkshop", () => {
  it("opens on Maps for an EDS cube", () => {
    render(<ElementalWorkshop />);
    expect(screen.getByText("Maps surface")).toBeVisible();
    expect(screen.getByRole("tab", { name: "Maps" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("routes EDS tabs to the EDS panels", () => {
    render(<ElementalWorkshop />);
    fireEvent.click(screen.getByRole("tab", { name: "Explore" }));
    expect(screen.getByText("EDS explore surface")).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "Quantify" }));
    expect(screen.getByText("EDS quantify surface")).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "Model fit" }));
    expect(screen.getByText("EDS model-fit surface")).toBeVisible();
  });

  it("drives the EELS workshop from the shared tab strip", () => {
    // An eV loss-energy range classifies as EELS.
    open(cube({ id: "eelscube", energy_first: 100, energy_last: 900, energy_units: "eV" }));
    render(<ElementalWorkshop />);
    expect(screen.getByDisplayValue("EELS")).toBeVisible();

    fireEvent.click(screen.getByRole("tab", { name: "Quantify" }));
    expect(screen.getByText(/EELS surface: Quantify/)).toBeVisible();
    // the nested workshop must not render a second tab strip
    expect(screen.queryByRole("tablist", { name: "EELS workflow" })).toBeNull();
  });

  it("offers Advanced only for EELS", () => {
    expect(screen.queryByRole("tab", { name: "Advanced" })).toBeNull();
    open(cube({ id: "e2", energy_first: 100, energy_last: 900, energy_units: "eV" }));
    render(<ElementalWorkshop />);
    expect(screen.getByRole("tab", { name: "Advanced" })).toBeVisible();
  });

  it("says plainly that EELS maps are not wired yet, rather than faking them", () => {
    open(cube({ id: "e3", energy_first: 100, energy_last: 900, energy_units: "eV" }));
    render(<ElementalWorkshop />);
    expect(screen.getByText(/not wired for EELS yet/)).toBeVisible();
    expect(screen.queryByText("Maps surface")).toBeNull();
  });

  it("lets the user re-route an ambiguous cube's modality", () => {
    render(<ElementalWorkshop />);
    const badge = screen.getByDisplayValue("EDS");
    fireEvent.change(badge, { target: { value: "eels" } });
    // the choice persists against the dataset, not the session
    expect(localStorage.getItem("fv_spectral_modalities")).toContain("eels");
  });
});
