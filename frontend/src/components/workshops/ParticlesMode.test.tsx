import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return {
    ...actual,
    analyzeParticles: vi.fn(),
    efdSimilarity: vi.fn(),
    fetchData16: vi.fn(),
  };
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
import { analyzeParticles, efdSimilarity, fetchData16 } from "../../lib/api";
import { useViewer } from "../../store/viewer";
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

// SHAPE_ANALYSIS_PLAN.md Wave 2 — GUI wiring: "find similar" (item #4).
describe("ParticlesMode — find similar", () => {
  function rowIds(container: HTMLElement): string[] {
    return Array.from(
      container.querySelectorAll<HTMLTableRowElement>("tbody tr"),
    ).map((tr) => tr.querySelector("td")?.textContent ?? "");
  }

  function rowById(container: HTMLElement, id: string): HTMLTableRowElement {
    const row = Array.from(
      container.querySelectorAll<HTMLTableRowElement>("tbody tr"),
    ).find((tr) => tr.querySelector("td")?.textContent === id);
    if (!row) throw new Error(`no row for id ${id}`);
    return row;
  }

  // Mocks MUST be configured before render — the raster fetch fires
  // synchronously from ParticlesMode's mount effect, so setting up the mock
  // afterwards only "works" by accident (a lingering mockResolvedValue left
  // over from an earlier test in the same run, which vi.clearAllMocks()
  // does not clear). Found by running this describe block in isolation
  // (vitest -t), which has no earlier test to leak from.
  async function setUpWithParticles(): Promise<HTMLElement> {
    vi.mocked(fetchData16).mockResolvedValue(raster());
    vi.mocked(analyzeParticles).mockResolvedValue({
      n_particles: 4,
      threshold: 0.5,
      labels: { id: "labels", meta: {} } as never,
      particles: particleRows(),
      unit: "nm",
    });
    const { container } = render(<ParticlesMode id="img" />);
    await waitFor(() => expect(fetchData16).toHaveBeenCalledWith("img"));
    fireEvent.click(screen.getByRole("button", { name: "Count" }));
    await waitFor(() => expect(rowIds(container).length).toBe(4));
    return container;
  }

  it("sorts ranked rows ascending by distance, the reference landing first", async () => {
    // Mutation tested: dropping the `.sort((a, b) => a.distance - b.distance)`
    // call in ParticlesTable.tsx (rendering `similarity.ranked` verbatim)
    // turned this RED — rows came back in the mock's [3, 2, 1] order instead
    // of [2, 1, 3]. Restored and green again.
    const container = await setUpWithParticles();

    vi.mocked(efdSimilarity).mockResolvedValue({
      ranked: [
        { id: 3, distance: 0.5 },
        { id: 2, distance: 0 }, // the reference — lands first at ≈0
        { id: 1, distance: 0.2 },
      ],
      skipped: [],
      n_harmonics: 10,
    });

    fireEvent.click(screen.getAllByRole("button", { name: "≈" })[1]); // particle id 2
    await waitFor(() => expect(rowIds(container)).toEqual(["2", "1", "3"]));
  });

  it("keeps skipped particles visible with '—' and the reason on hover", async () => {
    // Mutation tested: rendering skipped rows with the reason baked into the
    // cell TEXT instead of a `title` attribute turned this RED (no `title`
    // to assert on); restored to a `title`-only reason and green again.
    const container = await setUpWithParticles();

    vi.mocked(efdSimilarity).mockResolvedValue({
      ranked: [{ id: 1, distance: 0.012 }],
      skipped: [{ id: 4, reason: "no traceable outer contour" }],
      n_harmonics: 10,
    });

    fireEvent.click(screen.getAllByRole("button", { name: "≈" })[0]); // particle id 1
    await waitFor(() =>
      expect(screen.getByText(/ranked 1 · skipped 1/)).toBeInTheDocument(),
    );

    const distanceCell = rowById(container, "4").querySelectorAll("td")[1];
    expect(distanceCell.textContent).toBe("—");
    expect(distanceCell).toHaveAttribute(
      "title",
      "no traceable outer contour",
    );
    // the ranked row still shows a real distance, 3 sig figs
    expect(rowById(container, "1").querySelectorAll("td")[1].textContent).toBe(
      "0.0120",
    );
  });

  it("Clear exits similarity mode and restores the normal table's row order", async () => {
    // Mutation tested: making onClear a no-op (dropping `setSimilarity(null)`
    // from clearSimilarity) turned this RED — the distance column and
    // "ranked" status line stayed on screen after clicking Clear. Restored
    // and green again.
    const container = await setUpWithParticles();

    vi.mocked(efdSimilarity).mockResolvedValue({
      ranked: [
        { id: 2, distance: 0 },
        { id: 1, distance: 0.3 },
      ],
      skipped: [{ id: 4, reason: "no traceable outer contour" }],
      n_harmonics: 10,
    });
    fireEvent.click(screen.getAllByRole("button", { name: "≈" })[1]); // id 2
    await waitFor(() =>
      expect(screen.getByText(/ranked 2 · skipped 1/)).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole("button", { name: "Clear" }));

    await waitFor(() =>
      expect(rowIds(container)).toEqual(["1", "2", "3", "4"]),
    );
    expect(screen.queryByText(/ranked/)).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "≈" })).toHaveLength(4);
  });

  it("sends find-similar with the DISPLAYED run's exact params, ignoring later control edits", async () => {
    // Mutation tested: reading `polarity`/`minArea`/`watershed`/live-thresh
    // state directly in findSimilar (instead of the captured `runParams`)
    // turned this RED — the assertion below caught "bright"/99/false instead
    // of the run's actual "dark"/7/true. Restored to runParams and green.
    vi.mocked(fetchData16).mockResolvedValue(raster());
    vi.mocked(analyzeParticles).mockResolvedValue({
      n_particles: 4,
      threshold: 0.5,
      labels: { id: "labels", meta: {} } as never,
      particles: particleRows(),
      unit: "nm",
    });
    const { container } = render(<ParticlesMode id="img" />);
    await waitFor(() => expect(fetchData16).toHaveBeenCalledWith("img"));

    // Configure and run with a specific, non-default segmentation.
    fireEvent.click(screen.getByRole("button", { name: "dark" }));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "7" } });
    fireEvent.click(screen.getByLabelText("Split touching particles"));
    fireEvent.click(screen.getByRole("button", { name: "Count" }));
    await waitFor(() => expect(rowIds(container).length).toBe(4));

    // Edit the LIVE controls after the run — these must NOT leak into the
    // find-similar request; only the params that produced the displayed
    // table may.
    fireEvent.click(screen.getByRole("button", { name: "bright" }));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "99" } });
    fireEvent.click(screen.getByLabelText("Split touching particles"));
    fireEvent.change(screen.getByRole("slider"), { target: { value: "0.9" } });

    vi.mocked(efdSimilarity).mockResolvedValue({
      ranked: [],
      skipped: [],
      n_harmonics: 10,
    });
    fireEvent.click(screen.getAllByRole("button", { name: "≈" })[1]); // id 2

    await waitFor(() => expect(efdSimilarity).toHaveBeenCalled());
    expect(efdSimilarity).toHaveBeenCalledWith(
      "img",
      expect.objectContaining({
        threshold: 0.5, // realThr computed at Count time (vmin 0, thresh 0.5)
        polarity: "dark",
        minArea: 7,
        watershed: true,
        refId: 2,
      }),
    );
  });

  it("surfaces a 422 (undescribable reference) via the status idiom; the table stays usable", async () => {
    // Mutation tested: dropping the `.catch` handler in findSimilar (letting
    // the rejection go unhandled) turned this RED — status never updated.
    // Restored and green again.
    await setUpWithParticles();

    vi.mocked(efdSimilarity).mockRejectedValue(
      new Error(
        "reference region 3 cannot be described " +
          "(contour cannot support 10 harmonics) — nothing to rank against",
      ),
    );

    fireEvent.click(screen.getAllByRole("button", { name: "≈" })[2]); // id 3
    await waitFor(() =>
      expect(useViewer.getState().status).toBe(
        "find similar: reference region 3 cannot be described " +
          "(contour cannot support 10 harmonics) — nothing to rank against",
      ),
    );

    // still the ordinary table — never entered similarity mode
    expect(screen.getAllByRole("button", { name: "≈" })).toHaveLength(4);
    expect(screen.queryByText(/ranked/)).not.toBeInTheDocument();
  });

  it("exits similarity mode when the analysis is re-run (stale distances against a new segmentation)", async () => {
    // Mutation tested: removing the `setSimilarity(null)` call at the top of
    // count() turned this RED — the old distance column/status line stayed
    // on screen through the re-run. Restored and green again.
    await setUpWithParticles();

    vi.mocked(efdSimilarity).mockResolvedValue({
      ranked: [
        { id: 1, distance: 0 },
        { id: 2, distance: 0.4 },
      ],
      skipped: [],
      n_harmonics: 10,
    });
    fireEvent.click(screen.getAllByRole("button", { name: "≈" })[0]);
    await waitFor(() =>
      expect(screen.getByText(/ranked 2 · skipped 0/)).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole("button", { name: "Count" }));

    await waitFor(() =>
      expect(screen.queryByText(/ranked/)).not.toBeInTheDocument(),
    );
    expect(screen.getAllByRole("button", { name: "≈" })).toHaveLength(4);
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
