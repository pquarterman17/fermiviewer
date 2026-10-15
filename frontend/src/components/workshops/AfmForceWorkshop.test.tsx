// Force Curves workshop: helpers, the latest analysis wins, and force
// files from an open land in the force store (not the image library).
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  FORCE_VALUES,
  type ForceAnalysis,
  type ForceMeta,
  type ImageMeta,
} from "../../lib/api";
import { useAfmForce } from "../../store/afmForce";
import { useViewer } from "../../store/viewer";

vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return {
    ...actual,
    analyzeForceCurve: vi.fn(),
    listForceFiles: vi.fn(),
    forceMaps: vi.fn(),
    openSession: vi.fn(),
    uploadFiles: vi.fn(),
  };
});
vi.mock("uplot", () => ({
  default: Object.assign(class {
    destroy() {}
  }, { join: () => [[]] }),
}));

import {
  analyzeForceCurve,
  forceMaps,
  listForceFiles,
  openSession,
  uploadFiles,
  type ForceMapsResult,
} from "../../lib/api";
import AfmForceWorkshop, {
  calibrationSource,
  calibratedInvols,
  curveLabel,
  forceFitQuality,
  forceWarnings,
  formatModulus,
  formatValue,
} from "./AfmForceWorkshop";
import { forceTables } from "./ForceCurvePlot";

function force(id: string, extra: Partial<ForceMeta> = {}): ForceMeta {
  return {
    id, name: `${id}.ibw`, is_force: true, parser: "asylum", n_curves: 1, grid: null,
    map_pitch_nm: null, spring_constant: 0.1, invols: 50, deflection_unit: "nm",
    z_source: "Z sensor", ...extra,
  };
}

function image(id: string): ImageMeta {
  return {
    id, name: `${id}.tif`, kind: "image", shape: [2, 2], dtype: "float64",
    pixel_size: 1, pixel_unit: "nm", value_unit: "Pa", n_channels: null,
    energy_first: null, energy_last: null, energy_units: "", stage_tilt_deg: null, meta: {},
  };
}

function analysis(e: number): ForceAnalysis {
  const values = Object.fromEntries(FORCE_VALUES.map((k) => [k, 1])) as ForceAnalysis["values"];
  const units = Object.fromEntries(FORCE_VALUES.map((k) => [k, ""])) as ForceAnalysis["units"];
  values.youngs_modulus = e;
  values.fit_r2 = 0.99;
  values.fit_rms = 0.05;
  values.fit_points = 50;
  values.contact_slope = 1;
  values.noise_nm = 0.01;
  values.max_force = 10;
  units.fit_rms = "nN";
  return {
    values, units, fit: null, spring_constant: 0.1, invols: 50,
    baseline: { slope: 0, offset_nm: 0 },
    plot: { approach: { z: [2, 1, 3], force: [20, 10, 30], separation: [0, 1, 2] } },
  };
}

afterEach(() => {
  vi.clearAllMocks();
  useAfmForce.setState({ files: [], selectedId: null, error: null });
  useViewer.setState({ images: {}, order: [], activeId: null, tools: [] });
});

describe("AfmForceWorkshop helpers", () => {
  it("formats moduli with an SI prefix", () => {
    expect(formatModulus(2.5e6)).toBe("2.50 MPa");
    expect(formatModulus(3.1e9)).toBe("3.10 GPa");
    expect(formatModulus(12)).toBe("12.0 Pa");
    expect(formatModulus(null)).toBe("—");
    expect(formatValue("adhesion", 1.234, "nN")).toBe("1.23 nN");
    expect(formatValue("fit_points", 42, "")).toBe("42");
  });

  it("labels map curves by row and column", () => {
    expect(curveLabel(force("m", { n_curves: 6, grid: [2, 3] }), 4)).toBe(
      "curve 5 · row 2, col 2",
    );
    expect(curveLabel(force("l", { n_curves: 4 }), 0)).toBe("curve 1 of 4");
  });

  it("derives the InvOLS that makes a rigid contact slope 1", () => {
    expect(calibratedInvols(100, 3.36)).toBeCloseTo(29.76, 2);
    expect(calibratedInvols(null, 2)).toBeNull();
    expect(calibratedInvols(100, 0)).toBeNull();
  });

  it("labels calibration provenance and grades fit evidence", () => {
    const good = analysis(2e6);
    expect(calibrationSource(null, 0.1)).toBe("File");
    expect(calibrationSource(0.2, 0.1)).toBe("Override");
    expect(calibrationSource(null, null)).toBe("Unavailable");
    expect(forceFitQuality(good)).toBe("Excellent");

    good.values.fit_r2 = 0.82;
    good.values.fit_points = 7;
    good.values.contact_slope = 1.3;
    expect(forceFitQuality(good)).toBe("Poor");
    expect(forceWarnings(good)).toHaveLength(3);
  });

  it("sorts each trace along the chosen axis", () => {
    const [app] = forceTables(analysis(1), "z");
    expect(app.table).toEqual([[1, 2, 3], [10, 20, 30]]);
  });
});

describe("AfmForceWorkshop", () => {
  it("asks for a file when none is open", async () => {
    vi.mocked(listForceFiles).mockResolvedValue([]);
    await act(async () => {
      render(<AfmForceWorkshop />);
    });
    expect(screen.getByText(/Open a force-curve file/)).toBeTruthy();
    expect(screen.getByText(/session-only and are not saved in projects/i)).toBeVisible();
  });

  it("shows the latest analysis only", async () => {
    vi.useFakeTimers();
    try {
      let first!: (r: ForceAnalysis) => void;
      vi.mocked(listForceFiles).mockResolvedValue([force("f1")]);
      vi.mocked(analyzeForceCurve)
        .mockReturnValueOnce(new Promise((r) => { first = r; }))
        .mockResolvedValue(analysis(2e6));
      useAfmForce.setState({ files: [force("f1")], selectedId: "f1" });
      await act(async () => {
        render(<AfmForceWorkshop />);
      });
      await act(async () => {
        vi.advanceTimersByTime(200);
      });
      // a settings change supersedes the request still in flight
      fireEvent.change(screen.getByLabelText("Poisson ratio"), { target: { value: "0.3" } });
      await act(async () => {
        vi.advanceTimersByTime(200);
      });
      await act(async () => first(analysis(9e9)));
      expect(screen.getByText("2.00 MPa")).toBeTruthy();
      expect(screen.queryByText("9.00 GPa")).toBeNull();
      expect(vi.mocked(analyzeForceCurve).mock.calls.at(-1)?.[2].poisson).toBe(0.3);
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows calibration sources and fit-quality context", async () => {
    vi.useFakeTimers();
    try {
      vi.mocked(listForceFiles).mockResolvedValue([force("f1")]);
      vi.mocked(analyzeForceCurve).mockResolvedValue(analysis(2e6));
      useAfmForce.setState({ files: [force("f1")], selectedId: "f1" });
      await act(async () => { render(<AfmForceWorkshop />); });
      await act(async () => { vi.advanceTimersByTime(200); });

      expect(screen.getAllByText("File")).toHaveLength(3);
      expect(screen.getByText(/opening another project closes this file/i)).toBeVisible();
      expect(screen.getByText("Excellent")).toBeVisible();
      expect(screen.getByLabelText("Force plot annotations")).toHaveTextContent("Contact:");

      fireEvent.change(screen.getByLabelText("k (N/m)"), { target: { value: "0.2" } });
      expect(screen.getByRole("button", { name: "Export CSV" })).toBeDisabled();
      await act(async () => { vi.advanceTimersByTime(200); });
      expect(screen.getByText("Override")).toBeVisible();
      expect(screen.getByRole("button", { name: "Export CSV" })).toBeEnabled();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("force maps", () => {
  it("hold the file while they run and report on the file they ran on", async () => {
    let finish!: (r: ForceMapsResult) => void;
    const map = force("m1", { n_curves: 4, grid: [2, 2] });
    vi.mocked(listForceFiles).mockResolvedValue([map, force("f2")]);
    vi.mocked(analyzeForceCurve).mockResolvedValue(analysis(2e6));
    vi.mocked(forceMaps).mockReturnValue(new Promise((r) => { finish = r; }));
    useAfmForce.setState({ files: [map, force("f2")], selectedId: "m1" });
    await act(async () => {
      render(<AfmForceWorkshop />);
    });

    fireEvent.click(await screen.findByRole("button", { name: "Modulus / adhesion maps" }));
    expect(screen.getByLabelText("File")).toBeDisabled();
    expect(screen.getByRole("button", { name: "close force file" })).toBeDisabled();

    // a file opened elsewhere meanwhile takes the selection, not the result
    act(() => useAfmForce.getState().adopt([force("f3")]));
    const derived = image("modulus");
    await act(async () => finish({
      n: 4, failed: 0, units: {}, images: [derived],
      table: { youngs_modulus: [1e6, 2e6, 3e6, 4e6], adhesion: [], contact_z: [],
        max_force: [], fit_r2: [] },
    }));
    expect(useViewer.getState().images.modulus).toBeTruthy();
    expect(useViewer.getState().status).toMatch(/^m1\.ibw: 4\/4 curves/);
    expect(screen.getByLabelText("File")).not.toBeDisabled();
  });
});

describe("opening force files", () => {
  it("keeps them out of the image library and raises the workshop", async () => {
    const img: ImageMeta = {
      id: "i1", name: "topo.nid", kind: "image", shape: [4, 4], dtype: "float32",
      pixel_size: 1, pixel_unit: "nm", value_unit: "nm", n_channels: null,
      energy_first: null, energy_last: null, energy_units: "", stage_tilt_deg: null, meta: {},
    };
    vi.mocked(openSession).mockResolvedValue([img, force("f9")]);
    await useViewer.getState().openPaths(["/x/topo.nid"]);
    expect(useViewer.getState().order).toEqual(["i1"]);
    expect(useAfmForce.getState().selectedId).toBe("f9");
    expect(useViewer.getState().tools.map((t) => t.kind)).toContain("afmforce");
  });

  it("adopts the force file riding on an uploaded force map's image", async () => {
    const img: ImageMeta = {
      id: "i2", name: "map.nid", kind: "image", shape: [4, 4], dtype: "float32",
      pixel_size: 1, pixel_unit: "nm", value_unit: "nm", n_channels: null,
      energy_first: null, energy_last: null, energy_units: "", stage_tilt_deg: null, meta: {},
      force_file: force("f7", { n_curves: 4, grid: [2, 2] }),
    };
    vi.mocked(uploadFiles).mockResolvedValue([img]);
    await useViewer.getState().openFiles([new File(["x"], "map.nid")]);
    expect(useViewer.getState().order).toEqual(["i2"]);
    expect(useAfmForce.getState().selectedId).toBe("f7");
    expect(useViewer.getState().tools.map((t) => t.kind)).toContain("afmforce");
  });
});
