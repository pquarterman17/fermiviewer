// ToolsBrowser (unified pill panel): category pills filter which tool
// groups show. Store + transform-runner are mocked.

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const state = {
  activeId: "img1",
  captureMode: "none",
  setCaptureMode: vi.fn(),
};

vi.mock("../../store/viewer", () => ({
  useViewer: Object.assign((sel: (s: typeof state) => unknown) => sel(state), {
    getState: () => state,
  }),
}));

vi.mock("../../lib/transforms", () => ({
  runTransform: vi.fn(),
  defaultParams: () => ({}),
}));

import ToolsBrowser from "./ToolsBrowser";

describe("ToolsBrowser", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("All pill shows both measure and transform groups", () => {
    render(<ToolsBrowser />);
    expect(screen.getByText("Profiles & Distance")).toBeInTheDocument();
    expect(screen.getByText("Filters")).toBeInTheDocument();
    expect(screen.getByText("Transform Image")).toBeInTheDocument();
  });

  it("Measure pill hides transform groups", () => {
    render(<ToolsBrowser />);
    fireEvent.click(screen.getByText("Measure"));
    expect(screen.getByText("Profiles & Distance")).toBeInTheDocument();
    expect(screen.queryByText("Filters")).toBeNull();
    expect(screen.queryByText("Transform Image")).toBeNull();
  });

  it("Filter pill shows only the filter/segment groups", () => {
    render(<ToolsBrowser />);
    fireEvent.click(screen.getByText("Filter"));
    expect(screen.queryByText("Profiles & Distance")).toBeNull();
    expect(screen.getByText("Filters")).toBeInTheDocument();
    expect(screen.queryByText("Transform Image")).toBeNull();
  });
});
