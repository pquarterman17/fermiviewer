import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return { ...actual, analyzeParticles: vi.fn(), fetchData16: vi.fn() };
});

// Isolate ParticlesMode's data flow from PopulationHistogram's own
// rendering (uPlot + a live /api/analyze/distribution fetch — covered by
// its own colocated test) by rendering a probe that exposes exactly the
// props ParticlesMode computed and passed down.
vi.mock("../analysis/PopulationHistogram", () => ({
  default: ({
    values,
    unit,
    title,
  }: {
    values: number[];
    unit: string;
    title?: string;
  }) => (
    <div data-testid="population-histogram">
      {title} | unit=[{unit}] | values=[{values.join(",")}]
    </div>
  ),
}));

import type { ParticleRow } from "../../lib/api";
import { analyzeParticles, fetchData16 } from "../../lib/api";
import { useResults } from "../overlays/ResultsWindow";
import ParticlesMode, { countShapeClasses } from "./ParticlesMode";

afterEach(() => {
  vi.clearAllMocks();
  useResults.getState().close();
});

function raster() {
  return {
    w: 2,
    h: 2,
    vmin: 0,
    vmax: 1,
    nFrames: null,
    data: new Uint16Array([0, 1, 2, 3]),
  };
}

// One particle per shape class, per SHAPE_ANALYSIS_PLAN.md's frozen wire
// contract, plus one with a null (degenerate) aspect ratio.
function particleRows(): ParticleRow[] {
  return [
    {
      id: 1,
      area: 100,
      centroid: [1, 1],
      equiv_diameter: 11.28,
      mean_intensity: 5000,
      area_calibrated: 10,
      diameter_calibrated: 1.128,
      circularity: 0.91,
      aspect_ratio: 1.1,
      eccentricity: 0.4,
      orientation_rad: 0.2,
      solidity: 0.98,
      feret_max: 12,
      feret_max_calibrated: 1.2,
      shape_class: "sphere-like",
    },
    {
      id: 2,
      area: 60,
      centroid: [2, 2],
      equiv_diameter: 8.74,
      mean_intensity: 4000,
      area_calibrated: 6,
      diameter_calibrated: 0.874,
      circularity: 0.5,
      aspect_ratio: 3.2,
      eccentricity: 0.9,
      orientation_rad: -0.5,
      solidity: 0.95,
      feret_max: 20,
      feret_max_calibrated: 2.0,
      shape_class: "rod-like",
    },
    {
      id: 3,
      area: 40,
      centroid: [3, 3],
      equiv_diameter: 7.14,
      mean_intensity: 3000,
      area_calibrated: 4,
      diameter_calibrated: 0.714,
      circularity: 0.7,
      aspect_ratio: null,
      eccentricity: 0.6,
      orientation_rad: 0.9,
      solidity: 0.9,
      feret_max: 9,
      feret_max_calibrated: 0.9,
      shape_class: "intermediate",
    },
    {
      id: 4,
      area: 30,
      centroid: [4, 4],
      equiv_diameter: 6.18,
      mean_intensity: 2000,
      area_calibrated: 3,
      diameter_calibrated: 0.618,
      circularity: 0.6,
      aspect_ratio: 1.4,
      eccentricity: 0.5,
      orientation_rad: 1.4,
      solidity: 0.7,
      feret_max: 7,
      feret_max_calibrated: 0.7,
      shape_class: "aggregate",
    },
  ];
}

describe("ParticlesMode", () => {
  it("forwards the watershed split option to the endpoint", async () => {
    // The menu dialog that owned this option was replaced by this mode; if
    // the toggle stops reaching the API, touching particles silently merge
    // into one blob with no way for the user to separate them.
    vi.mocked(fetchData16).mockResolvedValue(raster());
    vi.mocked(analyzeParticles).mockResolvedValue({
      n_particles: 0,
      threshold: 0.5,
      labels: { id: "labels", meta: {} } as never,
      particles: [],
      unit: "nm",
    });

    render(<ParticlesMode id="img" />);
    await waitFor(() => expect(fetchData16).toHaveBeenCalledWith("img"));

    fireEvent.click(screen.getByLabelText("Split touching particles"));
    fireEvent.click(screen.getByRole("button", { name: "Count" }));

    await waitFor(() =>
      expect(analyzeParticles).toHaveBeenCalledWith(
        "img",
        expect.objectContaining({ watershed: true, polarity: "bright" }),
      ),
    );
  });

  it("defaults to no splitting so counts match the previous behaviour", async () => {
    vi.mocked(fetchData16).mockResolvedValue(raster());
    vi.mocked(analyzeParticles).mockResolvedValue({
      n_particles: 0,
      threshold: 0.5,
      labels: { id: "labels", meta: {} } as never,
      particles: [],
      unit: "nm",
    });

    render(<ParticlesMode id="img" />);
    await waitFor(() => expect(fetchData16).toHaveBeenCalledWith("img"));
    fireEvent.click(screen.getByRole("button", { name: "Count" }));

    await waitFor(() =>
      expect(analyzeParticles).toHaveBeenCalledWith(
        "img",
        expect.objectContaining({ watershed: false }),
      ),
    );
  });

  it("pushes the frozen contract's shape fields into the results table", async () => {
    vi.mocked(fetchData16).mockResolvedValue(raster());
    vi.mocked(analyzeParticles).mockResolvedValue({
      n_particles: 4,
      threshold: 0.5,
      labels: { id: "labels", meta: {} } as never,
      particles: particleRows(),
      unit: "nm",
    });

    render(<ParticlesMode id="img" />);
    await waitFor(() => expect(fetchData16).toHaveBeenCalledWith("img"));
    fireEvent.click(screen.getByRole("button", { name: "Count" }));
    await waitFor(() => expect(useResults.getState().table).not.toBeNull());

    const table = useResults.getState().table!;
    expect(table.columns).toEqual([
      "id",
      "area",
      "equiv ⌀",
      "mean I",
      "cx",
      "cy",
      "circ.",
      "AR",
      "class",
    ]);
    // row 1: circularity 2dp, aspect ratio 2dp, class verbatim
    expect(table.rows[0].slice(-3)).toEqual([0.91, 1.1, "sphere-like"]);
    // row 3: null aspect ratio renders as null, not 0 or a string
    expect(table.rows[2].slice(-3)).toEqual([0.7, null, "intermediate"]);
  });

  it("defaults the population picker to equivalent diameter, calibrated", async () => {
    vi.mocked(fetchData16).mockResolvedValue(raster());
    vi.mocked(analyzeParticles).mockResolvedValue({
      n_particles: 4,
      threshold: 0.5,
      labels: { id: "labels", meta: {} } as never,
      particles: particleRows(),
      unit: "nm",
    });

    render(<ParticlesMode id="img" />);
    await waitFor(() => expect(fetchData16).toHaveBeenCalledWith("img"));
    fireEvent.click(screen.getByRole("button", { name: "Count" }));

    const probe = await screen.findByTestId("population-histogram");
    expect(probe.textContent).toContain("unit=[nm]");
    expect(probe.textContent).toContain("values=[1.128,0.874,0.714,0.618]");
  });

  it("switches the population's values AND unit when the metric picker changes", async () => {
    vi.mocked(fetchData16).mockResolvedValue(raster());
    vi.mocked(analyzeParticles).mockResolvedValue({
      n_particles: 4,
      threshold: 0.5,
      labels: { id: "labels", meta: {} } as never,
      particles: particleRows(),
      unit: "nm",
    });

    render(<ParticlesMode id="img" />);
    await waitFor(() => expect(fetchData16).toHaveBeenCalledWith("img"));
    fireEvent.click(screen.getByRole("button", { name: "Count" }));
    await screen.findByTestId("population-histogram");

    // circularity is dimensionless: unit switches to "" (never "px")
    fireEvent.change(screen.getByLabelText("Population metric"), {
      target: { value: "circularity" },
    });
    await waitFor(() =>
      expect(screen.getByTestId("population-histogram").textContent).toContain(
        "values=[0.91,0.5,0.7,0.6]",
      ),
    );
    expect(screen.getByTestId("population-histogram").textContent).toContain("unit=[]");
  });

  it("excludes null aspect ratios from the population with a count note, never coercing to 0", async () => {
    vi.mocked(fetchData16).mockResolvedValue(raster());
    vi.mocked(analyzeParticles).mockResolvedValue({
      n_particles: 4,
      threshold: 0.5,
      labels: { id: "labels", meta: {} } as never,
      particles: particleRows(),
      unit: "nm",
    });

    render(<ParticlesMode id="img" />);
    await waitFor(() => expect(fetchData16).toHaveBeenCalledWith("img"));
    fireEvent.click(screen.getByRole("button", { name: "Count" }));
    await screen.findByTestId("population-histogram");

    fireEvent.change(screen.getByLabelText("Population metric"), {
      target: { value: "aspect_ratio" },
    });

    await waitFor(() =>
      expect(screen.getByTestId("population-histogram").textContent).toContain(
        // 3 particles have an aspect ratio; particle 3's null is dropped,
        // not coerced to 0
        "values=[1.1,3.2,1.4]",
      ),
    );
    expect(screen.getByText(/1 particle\(s\) excluded/)).toBeInTheDocument();
  });

  it("shows a per-class count line with the projection-caveat tooltip", async () => {
    vi.mocked(fetchData16).mockResolvedValue(raster());
    vi.mocked(analyzeParticles).mockResolvedValue({
      n_particles: 4,
      threshold: 0.5,
      labels: { id: "labels", meta: {} } as never,
      particles: particleRows(),
      unit: "nm",
    });

    render(<ParticlesMode id="img" />);
    await waitFor(() => expect(fetchData16).toHaveBeenCalledWith("img"));
    fireEvent.click(screen.getByRole("button", { name: "Count" }));

    const line = await screen.findByText(
      "1 sphere-like · 1 rod-like · 1 intermediate · 1 aggregate",
    );
    expect(line).toHaveAttribute(
      "title",
      expect.stringContaining("2D projection"),
    );
    expect(line.getAttribute("title")).toContain("end-on projects as a disk");
  });

  it("renders the orientation rose once particles exist", async () => {
    vi.mocked(fetchData16).mockResolvedValue(raster());
    vi.mocked(analyzeParticles).mockResolvedValue({
      n_particles: 4,
      threshold: 0.5,
      labels: { id: "labels", meta: {} } as never,
      particles: particleRows(),
      unit: "nm",
    });

    render(<ParticlesMode id="img" />);
    await waitFor(() => expect(fetchData16).toHaveBeenCalledWith("img"));
    expect(
      screen.queryByRole("img", { name: "Particle orientation half-rose" }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Count" }));
    await waitFor(() =>
      expect(
        screen.getByRole("img", { name: "Particle orientation half-rose" }),
      ).toBeInTheDocument(),
    );
  });
});

describe("countShapeClasses", () => {
  it("counts each particle into exactly one of the four classes", () => {
    expect(countShapeClasses(particleRows())).toEqual({
      "sphere-like": 1,
      "rod-like": 1,
      intermediate: 1,
      aggregate: 1,
    });
  });

  it("returns all-zero counts for an empty population", () => {
    expect(countShapeClasses([])).toEqual({
      "sphere-like": 0,
      "rod-like": 0,
      intermediate: 0,
      aggregate: 0,
    });
  });
});
