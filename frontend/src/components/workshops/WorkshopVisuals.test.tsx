// WS5b workshop redesign visuals: the Cross-section LayerStack band diagram
// and the Grains metric tiles. Both are pure re-presentations of existing
// analysis results, so these tests pin the data → visual mapping (band
// proportions, σ_erf rail assignment, optional-ASTM tile).

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { GrainResult, LayersResult } from "../../lib/api";
import { LayerStack } from "./LayersWorkshop";
import { GrainMetrics, paintedReadyCount } from "./StructureWorkshop";

function makeLayers(): LayersResult {
  return {
    axis: "y",
    layers_horizontal: true,
    tilt_deg: 0.4,
    coherence: 0.9,
    pixel_size: 1,
    unit: "nm",
    depth_pos: [],
    depth_profile: [],
    interfaces: [
      { position: 0, sigma_erf: 1.1, r_squared: 0.99, sigma_w: null, trace: null },
      { position: 6, sigma_erf: 1.82, r_squared: 0.98, sigma_w: null, trace: null },
    ],
    layers: [
      { index: 0, top: 0, bottom: 6.2, thickness: 6.2, thickness_std: 0.5 },
      { index: 1, top: 6.2, bottom: 18.6, thickness: 12.4, thickness_std: 0.3 },
    ],
  };
}

describe("LayerStack", () => {
  it("sizes each band by its thickness (flex-grow) and labels it", () => {
    const { container } = render(<LayerStack r={makeLayers()} />);
    const bands = Array.from(
      container.querySelectorAll<HTMLElement>(".fvd-layerstack-band"),
    );
    expect(bands).toHaveLength(2);
    // proportional: band grow factors equal the thicknesses
    expect(bands[0].style.flexGrow).toBe("6.2");
    expect(bands[1].style.flexGrow).toBe("12.4");
    expect(screen.getByText("Layer 1")).toBeInTheDocument();
    expect(screen.getByText("Layer 2")).toBeInTheDocument();
    // thickness ± std with the unit
    expect(screen.getByText(/±0\.5/)).toBeInTheDocument();
  });

  it("annotates the inter-layer boundary with the lower band's top σ_erf", () => {
    const { container } = render(<LayerStack r={makeLayers()} />);
    // one rail between the two bands, carrying interfaces[layers[1].index].sigma_erf
    const rails = container.querySelectorAll(".fvd-layerstack-iface");
    expect(rails).toHaveLength(1);
    expect(rails[0].textContent).toContain("1.82");
  });

  it("shows an em dash when a boundary σ_erf is null", () => {
    const r = makeLayers();
    r.interfaces[1] = { ...r.interfaces[1], sigma_erf: null };
    const { container } = render(<LayerStack r={r} />);
    expect(
      container.querySelector(".fvd-layerstack-iface")?.textContent,
    ).toContain("—");
  });
});

function makeGrains(overrides: Partial<GrainResult> = {}): GrainResult {
  return {
    n_grains: 34,
    method: "gradient",
    labels: {} as GrainResult["labels"],
    mean_diameter_px: 12.4,
    boundary_length_px: 0,
    boundary_network_px: 0,
    boundary_length_calibrated: null,
    n_boundary_segments: 0,
    n_triple_junctions: 41,
    astm_grain_size: 7.4,
    areas_px: [],
    perimeters_px: [],
    eccentricity: [],
    unit: "px",
    ...overrides,
  };
}

describe("GrainMetrics", () => {
  it("renders grains / mean ⌀ / ASTM / junctions tiles", () => {
    render(<GrainMetrics r={makeGrains()} />);
    expect(screen.getByText("34")).toBeInTheDocument();
    expect(screen.getByText("12.4 px")).toBeInTheDocument();
    expect(screen.getByText("G 7.4")).toBeInTheDocument();
    expect(screen.getByText("41")).toBeInTheDocument();
    expect(screen.getByText("grains")).toBeInTheDocument();
    expect(screen.getByText("mean ⌀")).toBeInTheDocument();
  });

  it("omits the ASTM tile when grain size is uncalibrated (null)", () => {
    render(<GrainMetrics r={makeGrains({ astm_grain_size: null })} />);
    expect(screen.queryByText("ASTM")).toBeNull();
    // the other tiles remain
    expect(screen.getByText("grains")).toBeInTheDocument();
    expect(screen.getByText("junctions")).toBeInTheDocument();
  });
});

describe("paintedReadyCount", () => {
  const stroke = (classId: number) => ({ classId });

  it("counts distinct painted classes, not strokes", () => {
    expect(paintedReadyCount([stroke(1), stroke(1), stroke(2)], [])).toBe(2);
  });

  it("excludes a class flagged as boundary (∅) even when painted", () => {
    // classes 1, 2, 3 painted but 3 is the boundary class → only 2 count
    expect(paintedReadyCount([stroke(1), stroke(2), stroke(3)], [3])).toBe(2);
  });

  it("is 0 for no strokes and 1 when only one class is painted", () => {
    expect(paintedReadyCount([], [])).toBe(0);
    expect(paintedReadyCount([stroke(1)], [])).toBe(1);
  });
});
