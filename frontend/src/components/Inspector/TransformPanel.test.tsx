// TransformPanel (GUI v2 phase 4): parameterless tools run on click;
// parameterised tools expand an inline form and run on Apply. The store,
// filter API, and geometry helpers are mocked so we assert the wiring.

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const state = {
  activeId: "img1",
  setStatus: vi.fn(),
  ingestDerived: vi.fn(),
};

vi.mock("../../store/viewer", () => ({
  useViewer: Object.assign((sel: (s: typeof state) => unknown) => sel(state), {
    getState: () => state,
  }),
}));

vi.mock("../../lib/api", () => ({
  applyFilter: vi.fn(() => Promise.resolve({ id: "d1", name: "deriv" })),
}));

vi.mock("../../lib/stageOps", () => ({
  applyGeometry: vi.fn(),
  cropToRoi: vi.fn(),
}));

import { applyFilter } from "../../lib/api";
import { applyGeometry } from "../../lib/stageOps";
import TransformPanel from "./TransformPanel";

describe("TransformPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("renders the three tool groups", () => {
    render(<TransformPanel />);
    expect(screen.getByText("Enhance")).toBeInTheDocument();
    expect(screen.getByText("Transform Image")).toBeInTheDocument();
    expect(screen.getByText("Segment")).toBeInTheDocument();
  });

  it("runs a parameterless tool immediately on click", () => {
    render(<TransformPanel />);
    fireEvent.click(screen.getByText("Rotate 90° CW"));
    expect(applyGeometry).toHaveBeenCalledWith("rotate90");
    // no inline form for parameterless tools
    expect(screen.queryByText("Apply")).toBeNull();
  });

  it("expands an inline form and applies a parameterised filter", () => {
    render(<TransformPanel />);
    // not run yet — only opens the form
    fireEvent.click(screen.getByText("Gaussian Blur"));
    expect(applyFilter).not.toHaveBeenCalled();
    expect(screen.getByText("Sigma (px)")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Apply"));
    expect(applyFilter).toHaveBeenCalledWith("img1", "gaussian", { sigma: 2 });
  });

  it("fuzzy-filters the list and shows an empty state", () => {
    render(<TransformPanel />);
    fireEvent.change(screen.getByPlaceholderText("Filter image tools…"), {
      target: { value: "zzz" },
    });
    expect(screen.getByText(/No tools match/)).toBeInTheDocument();
    expect(screen.queryByText("Gaussian Blur")).toBeNull();
  });
});
