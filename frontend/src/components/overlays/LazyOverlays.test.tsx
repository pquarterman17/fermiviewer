import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useParamDialog } from "../../store/params";
import { useViewer } from "../../store/viewer";

const overlays = [
  ["batchOpen", "batch"],
  ["calibOpen", "calibrations"],
  ["exportOpen", "export"],
  ["folderOpen", "folder"],
  ["galleryOpen", "gallery"],
  ["metaOpen", "metadata"],
  ["prefsOpen", "preferences"],
  ["shorts", "shortcuts"],
] as const;

vi.mock("./BatchDialog", () => ({
  default: () => <div data-testid="batch">batch</div>,
}));
vi.mock("./CalibrationManager", () => ({
  default: () => <div data-testid="calibrations">calibrations</div>,
}));
vi.mock("./ExportDialog", () => ({
  default: () => <div data-testid="export">export</div>,
}));
vi.mock("./FolderOpenDialog", () => ({
  default: () => <div data-testid="folder">folder</div>,
}));
vi.mock("./GalleryGrid", () => ({
  default: () => <div data-testid="gallery">gallery</div>,
}));
vi.mock("./MetadataDialog", () => ({
  default: () => <div data-testid="metadata">metadata</div>,
}));
vi.mock("./ParamDialog", () => ({
  default: () => <div data-testid="params">params</div>,
}));
vi.mock("./PrefsWindow", () => ({
  default: () => <div data-testid="preferences">preferences</div>,
}));
vi.mock("./ShortcutsOverlay", () => ({
  default: () => <div data-testid="shortcuts">shortcuts</div>,
}));

import LazyOverlays from "./LazyOverlays";

describe("LazyOverlays", () => {
  beforeEach(() => {
    useViewer.setState(Object.fromEntries(overlays.map(([key]) => [key, false])));
    useParamDialog.getState().close();
  });

  it("mounts each overlay only while its state is open", async () => {
    render(<LazyOverlays />);
    expect(screen.queryByTestId("export")).not.toBeInTheDocument();

    for (const [key, name] of overlays) {
      act(() => useViewer.setState({ [key]: true }));
      expect(await screen.findByTestId(name)).toBeInTheDocument();
      act(() => useViewer.setState({ [key]: false }));
      await waitFor(() => expect(screen.queryByTestId(name)).not.toBeInTheDocument());
    }

    act(() => {
      useParamDialog.getState().open("Parameters", [], () => undefined);
    });
    expect(await screen.findByTestId("params")).toBeInTheDocument();
    act(() => useParamDialog.getState().close());
    await waitFor(() => expect(screen.queryByTestId("params")).not.toBeInTheDocument());
  });
});
