// ProjectComparePanel — the W4 item 24 deliverable: result-vs-parameter
// table + plot + CSV export, plus item 23's SampleParamsEditor embedded for
// the selected sample. Mocks ResultVsParamPlot (uPlot needs a real canvas,
// which jsdom does not provide) so this test focuses on the wiring: sample
// picker, parameter picker, table, exclusions, and the CSV export button.
// Same store-mock pattern as Inspector/RegionsCard.test.tsx.

import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ImageGroup } from "../../lib/groups";
import type { RegionCandidate, RegionTableImage } from "../../lib/regionTable";

vi.mock("../plots/ResultVsParamPlot", () => ({
  default: () => <div data-testid="mock-plot" />,
}));

const setGroupParamsFn = vi.fn();
const setStatusFn = vi.fn();

function squareMeasure(id: string): RegionCandidate {
  return {
    id,
    kind: "polygon",
    pts: [
      { x: 0, y: 0 },
      { x: 1, y: 0 },
      { x: 1, y: 1 },
      { x: 0, y: 1 },
    ],
  };
}

function imageWithArea(area: number, unit = "um"): RegionTableImage {
  return { shape: [1, 1], pixel_size: Math.sqrt(area), pixel_unit: unit };
}

const HOT: ImageGroup = { id: "hot", name: "Hot", ids: ["a"], params: { temp: { value: 500, unit: "degC" } } };
const COLD: ImageGroup = { id: "cold", name: "Cold", ids: ["b"], params: { temp: { value: 100, unit: "degC" } } };
const NO_PARAM: ImageGroup = { id: "nopar", name: "NoParam", ids: ["c"] };

const state = {
  imageGroups: [HOT, COLD, NO_PARAM] as ImageGroup[],
  images: {
    a: imageWithArea(30),
    b: imageWithArea(10),
    c: imageWithArea(1),
  } as Record<string, RegionTableImage>,
  measures: {
    a: [squareMeasure("m1")],
    b: [squareMeasure("m2")],
    c: [squareMeasure("m3")],
  } as Record<string, RegionCandidate[]>,
  setGroupParams: setGroupParamsFn,
  setStatus: setStatusFn,
};

vi.mock("../../store/viewer", () => ({
  useViewer: Object.assign(
    (sel: (s: typeof state) => unknown) => sel(state),
    { getState: () => state },
  ),
}));

import ProjectComparePanel from "./ProjectComparePanel";

describe("ProjectComparePanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    state.imageGroups = [HOT, COLD, NO_PARAM];
  });

  it("shows an empty-state note when there are no sample groups", () => {
    state.imageGroups = [];
    render(<ProjectComparePanel />);
    expect(screen.getByText(/No sample groups yet/)).toBeInTheDocument();
  });

  it("defaults the parameter picker to the first available parameter and renders the table sorted by value", () => {
    render(<ProjectComparePanel />);
    expect(screen.getByLabelText("Parameter to plot")).toHaveValue("temp");
    const rows = screen.getAllByRole("row").slice(1); // drop header
    // Cold (100) before Hot (500) — ascending, not group-creation order
    expect(rows[0]).toHaveTextContent("Cold");
    expect(rows[1]).toHaveTextContent("Hot");
  });

  it("carries n in the table and derives the unit from the data", () => {
    render(<ProjectComparePanel />);
    expect(screen.getByText("temp_degC")).toBeInTheDocument();
    expect(screen.getByText(/area \(um²\) mean/)).toBeInTheDocument();
    const rows = screen.getAllByRole("row").slice(1);
    // n is the 3rd cell (sample, param, n, mean+-sd) -> each sample has
    // exactly 1 region measured
    expect(within(rows[0]).getAllByRole("cell")[2]).toHaveTextContent("1");
  });

  it("reports the sample with no parameter as excluded, with a reason, not silently dropped", () => {
    render(<ProjectComparePanel />);
    expect(screen.getByText(/1 sample\(s\) excluded/)).toBeInTheDocument();
    expect(screen.getByText(/NoParam: no "temp" parameter set/)).toBeInTheDocument();
  });

  it("embeds the parameter editor for the selected sample", () => {
    render(<ProjectComparePanel />);
    // first sample ("Hot") selected by default
    expect(screen.getByTestId("sample-params-editor")).toHaveTextContent("Hot");
  });

  it("switches the embedded editor when a different sample is picked", () => {
    render(<ProjectComparePanel />);
    fireEvent.change(screen.getByLabelText("Sample to edit"), {
      target: { value: "cold" },
    });
    expect(screen.getByTestId("sample-params-editor")).toHaveTextContent("Cold");
  });

  it("exports a CSV whose header states the real units and rows carry sample, n, mean, sd", () => {
    globalThis.URL.createObjectURL = vi.fn(() => "blob:mock");
    globalThis.URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    let capturedBlob: Blob | null = null;
    globalThis.URL.createObjectURL = vi.fn((b: Blob) => {
      capturedBlob = b;
      return "blob:mock";
    });
    render(<ProjectComparePanel />);
    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    expect(capturedBlob).not.toBeNull();
    return capturedBlob!.text().then((text) => {
      expect(text).toContain("sample,temp_degC,n,area_um2_mean,area_um2_sd");
      expect(text).toContain("Cold,100,1,10,0");
      expect(text).toContain("Hot,500,1,30,0");
    });
  });
});
