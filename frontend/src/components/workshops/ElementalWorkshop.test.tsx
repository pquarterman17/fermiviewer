import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { EdsQuantResult, ImageMeta } from "../../lib/api";
import type { Species } from "../../lib/spectrum/species";
import { useSpecies } from "../../store/species";
import { useViewer } from "../../store/viewer";
import ElementalWorkshop from "./ElementalWorkshop";

vi.mock("../elemental/MapsTab", () => ({
  default: ({ quantBySymbol }: { quantBySymbol?: Record<string, number> }) => (
    <>
      <div>Maps surface</div>
      <span data-testid="maps-quant">
        {Object.keys(quantBySymbol ?? {}).join(",")}
      </span>
    </>
  ),
}));
vi.mock("../elemental/EelsMapsTab", () => ({
  default: () => <div>EELS maps surface</div>,
}));
vi.mock("./EdsSpectrumImage", () => ({
  default: () => <div>EDS explore surface</div>,
}));
vi.mock("./EdsModelFit", () => ({
  default: ({ elements }: { elements: string }) => (
    <>
      <div>EDS model-fit surface</div>
      <span data-testid="model-elements">{elements}</span>
    </>
  ),
}));
vi.mock("./EdsQuantifyPanel", () => ({
  default: ({
    elements,
    onElements,
    onResult,
  }: {
    elements: string;
    onElements: (v: string) => void;
    onResult: (r: EdsQuantResult | null) => void;
  }) => (
    <>
      <div>EDS quantify surface</div>
      <input
        aria-label="quant elements"
        value={elements}
        onChange={(e) => onElements(e.target.value)}
      />
      <button
        onClick={() =>
          onResult({
            elements: ["Ag"],
            mean_atomic_pct: [100],
          } as unknown as EdsQuantResult)
        }
      >
        fake quantify
      </button>
    </>
  ),
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
  useSpecies.setState({ byImage: {}, quantElementsByImage: {} });
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

  it("renders the EELS maps tab for an EELS cube, not the EDS one", () => {
    open(cube({ id: "e3", energy_first: 100, energy_last: 900, energy_units: "eV" }));
    render(<ElementalWorkshop />);
    expect(screen.getByText("EELS maps surface")).toBeVisible();
    expect(screen.queryByText("Maps surface")).toBeNull();
  });

  it("lets the user re-route an ambiguous cube's modality", () => {
    render(<ElementalWorkshop />);
    const badge = screen.getByDisplayValue("EDS");
    fireEvent.change(badge, { target: { value: "eels" } });
    // the choice persists against the dataset, not the session
    expect(localStorage.getItem("fv_spectral_modalities")).toContain("eels");
  });

  it("switches the workspace when the modality dropdown changes", () => {
    render(<ElementalWorkshop />);
    expect(screen.getByText("Maps surface")).toBeVisible();
    fireEvent.change(screen.getByDisplayValue("EDS"), {
      target: { value: "eels" },
    });
    // it used to write localStorage only and leave the EDS surface on screen
    expect(screen.getByText("EELS maps surface")).toBeVisible();
    expect(screen.getByDisplayValue("EELS")).toBeVisible();
  });

  it("fits the identified species, not a hardcoded Fe/O, and keeps edits per image", () => {
    useSpecies.setState({
      byImage: {
        cube: [
          { id: "a", symbol: "Al" },
          { id: "b", symbol: "Ag" },
          { id: "c", symbol: "Ag" },
        ] as unknown as Species[],
      },
    });
    const first = render(<ElementalWorkshop />);
    fireEvent.click(screen.getByRole("tab", { name: "Model fit" }));
    expect(screen.getByTestId("model-elements")).toHaveTextContent(/^Al, Ag$/);
    fireEvent.click(screen.getByRole("tab", { name: "Quantify" }));
    fireEvent.change(screen.getByLabelText("quant elements"), {
      target: { value: "Al, Ag, O" },
    });
    first.unmount();
    // closing and reopening the workspace keeps the list
    render(<ElementalWorkshop />);
    fireEvent.click(screen.getByRole("tab", { name: "Model fit" }));
    expect(screen.getByTestId("model-elements")).toHaveTextContent("Al, Ag, O");
  });

  it("does not carry a Quantify result over to another image", () => {
    render(<ElementalWorkshop />);
    fireEvent.click(screen.getByRole("tab", { name: "Quantify" }));
    fireEvent.click(screen.getByText("fake quantify"));
    fireEvent.click(screen.getByRole("tab", { name: "Maps" }));
    expect(screen.getByTestId("maps-quant")).toHaveTextContent("Ag");
    act(() => {
      const other = cube({ id: "other", name: "other.bcf" });
      useViewer.setState((s) => ({
        images: { ...s.images, other },
        order: [...s.order, "other"],
        activeId: "other",
      }));
    });
    expect(screen.getByTestId("maps-quant")).toHaveTextContent(/^$/);
  });
});
