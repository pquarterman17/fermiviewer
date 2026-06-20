// FolderOpenDialog: when launched from a folder, lists its supported
// images (pre-checked) and opens the selected ones by server-side path.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const openPaths = vi.fn((..._a: unknown[]) => Promise.resolve());
const openFiles = vi.fn((..._a: unknown[]) => Promise.resolve());

const state = {
  folderOpen: true,
  setFolderOpen: vi.fn(),
  launchContext: {
    dir: "C:\\data\\session",
    files: [
      { name: "a.dm4", path: "C:\\data\\session\\a.dm4" },
      { name: "b.tif", path: "C:\\data\\session\\b.tif" },
    ],
  },
  openPaths,
  openFiles,
  setStatus: vi.fn(),
};

vi.mock("../../store/viewer", () => ({
  useViewer: Object.assign((sel: (s: typeof state) => unknown) => sel(state), {
    getState: () => state,
  }),
}));

import FolderOpenDialog from "./FolderOpenDialog";

describe("FolderOpenDialog", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists the launch folder's files, pre-checked", () => {
    render(<FolderOpenDialog />);
    expect(screen.getByText("C:\\data\\session")).toBeTruthy();
    const boxes = screen.getAllByRole("checkbox") as HTMLInputElement[];
    expect(boxes).toHaveLength(2);
    expect(boxes.every((b) => b.checked)).toBe(true);
  });

  it("opens the selected paths and closes", async () => {
    render(<FolderOpenDialog />);
    fireEvent.click(screen.getByRole("button", { name: /Open/ }));
    await waitFor(() => expect(openPaths).toHaveBeenCalled());
    expect(openPaths).toHaveBeenCalledWith([
      "C:\\data\\session\\a.dm4",
      "C:\\data\\session\\b.tif",
    ]);
    expect(state.setFolderOpen).toHaveBeenCalledWith(false);
  });

  it("excludes an unchecked file from the open set", async () => {
    render(<FolderOpenDialog />);
    const boxes = screen.getAllByRole("checkbox") as HTMLInputElement[];
    fireEvent.click(boxes[0]); // uncheck a.dm4
    fireEvent.click(screen.getByRole("button", { name: /Open/ }));
    await waitFor(() => expect(openPaths).toHaveBeenCalled());
    expect(openPaths).toHaveBeenCalledWith(["C:\\data\\session\\b.tif"]);
  });
});
