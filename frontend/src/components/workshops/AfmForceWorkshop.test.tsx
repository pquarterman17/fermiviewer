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
  };
});
vi.mock("uplot", () => ({
  default: Object.assign(class {
    destroy() {}
  }, { join: () => [[]] }),
}));

import { analyzeForceCurve, listForceFiles, openSession } from "../../lib/api";
import AfmForceWorkshop, {
  calibratedInvols,
  curveLabel,
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

function analysis(e: number): ForceAnalysis {
  const values = Object.fromEntries(FORCE_VALUES.map((k) => [k, 1])) as ForceAnalysis["values"];
  const units = Object.fromEntries(FORCE_VALUES.map((k) => [k, ""])) as ForceAnalysis["units"];
  values.youngs_modulus = e;
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
});
