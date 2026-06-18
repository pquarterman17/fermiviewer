// HistoryCard (WS4d): renders the active image's step list, marks the
// current step, and reverts the display on clicking an earlier one.

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const revertHistory = vi.fn();
const state = {
  activeId: "img1",
  history: {
    img1: [
      { id: 1, field: "open", label: "Opened", display: {} },
      { id: 2, field: "cmap", label: "Colormap → viridis", display: {} },
      { id: 3, field: "gamma", label: "Gamma 0.80", display: {} },
    ],
  },
  historyAt: { img1: 2 },
  revertHistory,
};
vi.mock("../../store/viewer", () => ({
  useViewer: Object.assign((sel: (s: typeof state) => unknown) => sel(state), {
    getState: () => state,
  }),
}));

import HistoryCard from "./HistoryCard";

describe("HistoryCard (WS4d)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists steps, marks the current one, and reverts on click", () => {
    render(<HistoryCard />);
    expect(screen.getByText("Opened")).toBeInTheDocument();
    expect(screen.getByText("Colormap → viridis")).toBeInTheDocument();
    expect(screen.getByText("now")).toBeInTheDocument(); // current marker

    // clicking an earlier step reverts to its index
    fireEvent.click(screen.getByText("Colormap → viridis"));
    expect(revertHistory).toHaveBeenCalledWith("img1", 1);

    // clicking the current step is a no-op
    fireEvent.click(screen.getByText("Gamma 0.80"));
    expect(revertHistory).toHaveBeenCalledTimes(1);
  });
});
