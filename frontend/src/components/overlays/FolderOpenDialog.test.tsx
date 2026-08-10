// FolderOpenDialog: when launched from a folder, lists its supported
// images (pre-checked) and opens the selected ones by server-side path.
// Folder import (items 2-3) is wired to lib/folderImport's importFolders,
// which is mocked here — its own seeding/orchestration behavior is
// covered by folderImport.test.ts against the real store.

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../lib/api", () => ({
  supportedExtensions: () => Promise.resolve([".tif", ".dm4"]),
}));

vi.mock("../../lib/folderImport", () => ({
  importFolders: vi.fn(() => Promise.resolve()),
}));

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

import { importFolders } from "../../lib/folderImport";
import FolderOpenDialog from "./FolderOpenDialog";

describe("FolderOpenDialog", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists the launch folder's files, pre-checked", () => {
    render(<FolderOpenDialog />);
    expect(screen.getByText("C:\\data\\session")).toBeTruthy();
    const boxes = within(screen.getByRole("list")).getAllByRole(
      "checkbox",
    ) as HTMLInputElement[];
    expect(boxes).toHaveLength(2);
    expect(boxes.every((b) => b.checked)).toBe(true);
  });

  it("opens the selected paths and closes", async () => {
    render(<FolderOpenDialog />);
    fireEvent.click(screen.getByRole("button", { name: /^Open/ }));
    await waitFor(() => expect(openPaths).toHaveBeenCalled());
    expect(openPaths).toHaveBeenCalledWith([
      "C:\\data\\session\\a.dm4",
      "C:\\data\\session\\b.tif",
    ]);
    expect(state.setFolderOpen).toHaveBeenCalledWith(false);
  });

  it("excludes an unchecked file from the open set", async () => {
    render(<FolderOpenDialog />);
    const boxes = within(screen.getByRole("list")).getAllByRole(
      "checkbox",
    ) as HTMLInputElement[];
    fireEvent.click(boxes[0]); // uncheck a.dm4
    fireEvent.click(screen.getByRole("button", { name: /^Open/ }));
    await waitFor(() => expect(openPaths).toHaveBeenCalled());
    expect(openPaths).toHaveBeenCalledWith(["C:\\data\\session\\b.tif"]);
  });

  it("disables the Import button until a folder path is entered", () => {
    render(<FolderOpenDialog />);
    const importBtn = screen.getByRole("button", { name: /^Import folder/ });
    expect(importBtn).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Import folder(s)"), {
      target: { value: "/data/400C" },
    });
    expect(importBtn).toBeEnabled();
  });

  it("shows the recursion/cap/skip policy up front, before any import (item 5)", () => {
    render(<FolderOpenDialog />);
    expect(screen.getByText(/recurses fully/)).toBeTruthy();
    expect(screen.getByText(/cap at 500 files/)).toBeTruthy();
  });

  it("imports the typed folder paths, split on newlines, with the merge flag", async () => {
    render(<FolderOpenDialog />);
    fireEvent.change(screen.getByLabelText("Import folder(s)"), {
      target: { value: "/data/400C\n/data/500C\n" },
    });
    fireEvent.click(screen.getByText("Merge into one group"));
    fireEvent.click(screen.getByRole("button", { name: /^Import folder/ }));
    await waitFor(() => expect(importFolders).toHaveBeenCalled());
    expect(vi.mocked(importFolders)).toHaveBeenCalledWith(
      ["/data/400C", "/data/500C"],
      { merge: true },
    );
    expect(state.setFolderOpen).toHaveBeenCalledWith(false);
  });
});
