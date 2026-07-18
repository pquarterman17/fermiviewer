import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../lib/api", () => ({
  supportedExtensions: () => Promise.resolve([".dm4", ".tif"]),
}));

const openFiles = vi.fn(() => Promise.resolve());
const state = {
  launchContext: null as null | { files: { name: string; path: string }[] },
  setFolderOpen: vi.fn(),
  openFiles,
  setStatus: vi.fn(),
};

vi.mock("../../store/viewer", () => ({
  useViewer: Object.assign((sel: (s: typeof state) => unknown) => sel(state), {
    getState: () => state,
  }),
}));

import EmptyStage from "./EmptyStage";

describe("EmptyStage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    state.launchContext = null;
  });

  it("presents a clear open and drop affordance", () => {
    render(<EmptyStage />);
    expect(
      screen.getByRole("heading", { name: "Open a microscopy dataset" }),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Open image…" })).toBeVisible();
    expect(screen.getByText(/drop files anywhere/)).toBeVisible();
  });

  it("opens the launch-folder dialog when folder context is available", () => {
    state.launchContext = { files: [{ name: "a.dm4", path: "C:\\a.dm4" }] };
    render(<EmptyStage />);
    fireEvent.click(screen.getByRole("button", { name: "Open image…" }));
    expect(state.setFolderOpen).toHaveBeenCalledWith(true);
  });

  it("uploads files selected from the native picker", async () => {
    const { container } = render(<EmptyStage />);
    const input = container.querySelector("input[type=file]") as HTMLInputElement;
    const file = new File(["pixels"], "sample.tif", { type: "image/tiff" });
    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => expect(openFiles).toHaveBeenCalled());
  });
});
