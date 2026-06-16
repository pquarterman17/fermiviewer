// BatchDialog: build a recipe and run it across targets. Store + applyFilter
// are mocked; we assert the chained execution (each step's output id feeds the
// next) and that only the final image of each chain is ingested.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const applyFilter = vi.fn();
vi.mock("../../lib/api", () => ({
  applyFilter: (...args: unknown[]) => applyFilter(...args),
}));

vi.mock("./ParamDialog", () => ({ askParams: vi.fn() }));

const state = {
  batchOpen: true,
  setBatchOpen: vi.fn(),
  selected: ["a", "b"],
  order: ["a", "b"],
  images: { a: { name: "a.dm4" }, b: { name: "b.dm4" } },
  ingestDerived: vi.fn(),
  setStatus: vi.fn(),
};
vi.mock("../../store/viewer", () => ({
  useViewer: Object.assign((sel: (s: typeof state) => unknown) => sel(state), {
    getState: () => state,
  }),
}));

import BatchDialog from "./BatchDialog";

describe("BatchDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // each filter returns a fresh derived id so chaining is observable
    applyFilter.mockImplementation((id: string, kind: string) =>
      Promise.resolve({ id: `${id}_${kind}`, name: `${id}.dm4` }),
    );
  });

  it("runs a single no-param step once per target and ingests the finals", async () => {
    render(<BatchDialog />);
    fireEvent.click(screen.getByText("+ Plane Level"));
    expect(screen.getByText("Plane Level")).toBeInTheDocument(); // step added

    fireEvent.click(screen.getByText(/Run batch/));
    await waitFor(() => expect(state.ingestDerived).toHaveBeenCalled());

    expect(applyFilter).toHaveBeenCalledTimes(2); // one per target
    expect(applyFilter).toHaveBeenCalledWith("a", "plane_level", {});
    expect(applyFilter).toHaveBeenCalledWith("b", "plane_level", {});
    expect(state.ingestDerived.mock.calls[0][0]).toHaveLength(2);
    expect(state.setStatus).toHaveBeenCalled();
  });

  it("chains steps: each step runs on the previous step's output", async () => {
    render(<BatchDialog />);
    fireEvent.click(screen.getByText("+ Plane Level"));
    fireEvent.click(screen.getByText("+ Rotate 90° CW"));

    fireEvent.click(screen.getByText(/Run batch/));
    await waitFor(() => expect(state.ingestDerived).toHaveBeenCalled());

    expect(applyFilter).toHaveBeenCalledTimes(4); // 2 steps × 2 targets
    // target "a": step 1 on "a", step 2 on step-1's output id
    expect(applyFilter).toHaveBeenCalledWith("a", "plane_level", {});
    expect(applyFilter).toHaveBeenCalledWith("a_plane_level", "rotate90", {});
  });

  it("removing a step drops it from the recipe", () => {
    render(<BatchDialog />);
    fireEvent.click(screen.getByText("+ Plane Level"));
    expect(screen.getByText("Plane Level")).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("Remove step"));
    expect(screen.queryByText("Plane Level")).toBeNull();
  });
});
