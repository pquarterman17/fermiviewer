// ExportDialog (WS4c): the report-caption UI composes the user caption +
// the optional auto metadata line and threads it into the export. The
// export/preview pipelines themselves are unit-tested in lib/export.test.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const exportActive = vi.fn((..._a: unknown[]) => Promise.resolve("img.png"));
const previewActive = vi.fn((..._a: unknown[]) =>
  Promise.resolve(new Blob(["x"])),
);
vi.mock("../../lib/export", () => ({
  exportActive: (...a: unknown[]) => exportActive(...a),
  previewActive: (...a: unknown[]) => previewActive(...a),
}));

vi.mock("../../lib/prefs", () => ({
  loadPrefs: () => ({
    exportFormat: "png",
    exportScale: 1,
    exportScaleBar: true,
    exportMeasures: true,
    exportColorbar: false,
  }),
}));

const state = {
  exportOpen: true,
  setExportOpen: vi.fn(),
  activeId: "img1",
  images: {
    img1: {
      id: "img1",
      name: "img.dm4",
      kind: "image",
      shape: [12, 16],
      pixel_size: 0.5,
      pixel_unit: "nm",
    },
  },
  measures: { img1: [] },
  setStatus: vi.fn(),
};
vi.mock("../../store/viewer", () => ({
  useViewer: Object.assign((sel: (s: typeof state) => unknown) => sel(state), {
    getState: () => state,
  }),
}));

import ExportDialog from "./ExportDialog";

describe("ExportDialog caption (WS4c)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    globalThis.URL.createObjectURL = vi.fn(() => "blob:x");
    globalThis.URL.revokeObjectURL = vi.fn();
  });

  it("composes the user caption + metadata line and exports it", async () => {
    render(<ExportDialog />);
    fireEvent.change(
      screen.getByPlaceholderText("e.g. Fig 1 · 80 kx · HAADF"),
      { target: { value: "Fig 1 · HAADF" } },
    );
    fireEvent.click(screen.getByRole("checkbox", { name: /Metadata line/ }));

    fireEvent.click(screen.getByRole("button", { name: "Export" }));
    await waitFor(() => expect(exportActive).toHaveBeenCalled());

    expect(exportActive).toHaveBeenCalledWith(
      expect.objectContaining({
        caption: "Fig 1 · HAADF\nimg.dm4 · 16×12 px · 0.5 nm/px",
      }),
    );
  });

  it("renders a live preview from the same export pipeline", async () => {
    render(<ExportDialog />);
    await waitFor(() => expect(previewActive).toHaveBeenCalled());
  });
});
