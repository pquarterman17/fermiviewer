// WS5b workshop redesign visuals: the Cross-section LayerStack band diagram
// and the Grains metric tiles. Both are pure re-presentations of existing
// analysis results, so these tests pin the data → visual mapping (band
// proportions, σ_erf rail assignment, optional-ASTM tile).

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type {
  GrainPreviewClass,
  GrainResult,
  LayerInterface,
  LayersResult,
} from "../../lib/api";
import LayersRoughnessDetail from "./LayersRoughnessDetail";
import { LayerStack } from "./LayersWorkshop";
import { GrainMetrics } from "./AnalysisQualityCard";
import {
  paintedReadyCount,
  TrainedPreviewLegend,
} from "./StructureWorkshop";

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
      { position: 0, sigma_erf: 1.1, r_squared: 0.99, sigma_w: null, trace: null, roughness: null },
      { position: 6, sigma_erf: 1.82, r_squared: 0.98, sigma_w: null, trace: null, roughness: null },
    ],
    layers: [
      { index: 0, top: 0, bottom: 6.2, thickness: 6.2, thickness_std: 0.5, conformality: null },
      { index: 1, top: 6.2, bottom: 18.6, thickness: 12.4, thickness_std: 0.3, conformality: null },
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

describe("TrainedPreviewLegend", () => {
  const classes: GrainPreviewClass[] = [
    { class_id: 1, fraction: 0.62, is_boundary: false },
    { class_id: 2, fraction: 0.31, is_boundary: false },
    { class_id: 3, fraction: 0.07, is_boundary: true },
  ];

  it("renders a labelled row per class with rounded percentages", () => {
    const { container } = render(<TrainedPreviewLegend classes={classes} />);
    expect(
      container.querySelectorAll(".fvd-legend-item"),
    ).toHaveLength(3);
    expect(screen.getByText("Class 1")).toBeInTheDocument();
    expect(screen.getByText("62%")).toBeInTheDocument();
    expect(screen.getByText("31%")).toBeInTheDocument();
  });

  it("marks a boundary class with the ∅ prefix", () => {
    render(<TrainedPreviewLegend classes={classes} />);
    // boundary class 3 gets the ∅ prefix; non-boundary classes do not
    expect(screen.getByText("∅ Class 3")).toBeInTheDocument();
    expect(screen.getByText("7%")).toBeInTheDocument();
  });
});

describe("LayersRoughnessDetail", () => {
  const iface = (over: Partial<LayerInterface> = {}): LayerInterface => ({
    position: 60,
    sigma_erf: 2.5,
    r_squared: 0.98,
    sigma_w: 1.5,
    trace: [60, 61, 59],
    roughness: {
      sigma_ci: [1.2, 1.9],
      sigma_raw: 1.6,
      noise_floor: 0.4,
      quality: 0.97,
      xi: 24,
      hurst: 0.85,
      sigma_chem: 2.0,
      psd_wavelength: [],
      psd_power: [],
    },
    ...over,
  });

  it("shows sigma_w with its CI plus xi, Hurst and sigma_chem tiles", () => {
    const { container } = render(
      <LayersRoughnessDetail iface={iface()} index={0} unit="nm" foilT={null} />,
    );
    expect(container.querySelectorAll(".fvd-metric")).toHaveLength(4);
    expect(screen.getByText("1.50")).toBeInTheDocument();        // sigma_w
    expect(screen.getByText(/\[1\.20–1\.90\]/)).toBeInTheDocument();
    expect(screen.getByText("24")).toBeInTheDocument();          // xi
    expect(screen.getByText("0.85")).toBeInTheDocument();        // Hurst
    expect(screen.getByText("2.00")).toBeInTheDocument();        // sigma_chem
    expect(screen.getByText(/97% of columns OK/)).toBeInTheDocument();
  });

  it("warns when the trace quality is poor", () => {
    const bad = iface();
    bad.roughness!.quality = 0.55;
    render(<LayersRoughnessDetail iface={bad} index={0} unit="nm" foilT={null} />);
    expect(screen.getByText(/noisy trace/)).toBeInTheDocument();
  });

  it("points at the waviness toggle when no trace was computed", () => {
    render(
      <LayersRoughnessDetail
        iface={iface({ roughness: null })}
        index={0}
        unit="nm"
        foilT={null}
      />,
    );
    expect(screen.getByText(/re-analyze/)).toBeInTheDocument();
  });
});
