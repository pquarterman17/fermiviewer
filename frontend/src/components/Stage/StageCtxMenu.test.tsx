// ScaleBarCtxMenu: the stage's scale-bar right-click menu. Covers the new
// top-of-menu "Copy Image" entry (owner feature: right-click copy includes
// on-screen annotations by default, governed by a preference) — it must
// render only when there's an active raster image, call the shared
// copyActive() seam, and close the menu.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const state: {
  toggleScaleBar: ReturnType<typeof vi.fn>;
  scaleBarVisible: boolean;
  activeId: string | null;
  images: Record<string, { kind: string; pixel_size: number | null; pixel_unit: string }>;
  setScaleBar: ReturnType<typeof vi.fn>;
  setStatus: ReturnType<typeof vi.fn>;
} = {
  toggleScaleBar: vi.fn(),
  scaleBarVisible: true,
  activeId: "img1",
  images: {
    img1: { kind: "image", pixel_size: null, pixel_unit: "px" },
  },
  setScaleBar: vi.fn(),
  setStatus: vi.fn(),
};

vi.mock("../../store/viewer", () => ({
  useViewer: Object.assign((sel: (s: typeof state) => unknown) => sel(state), {
    getState: () => state,
  }),
}));

const copyActive = vi.fn((..._args: unknown[]) => Promise.resolve());
vi.mock("../../lib/export", () => ({
  copyActive: (...args: unknown[]) => copyActive(...args),
}));

import { ScaleBarCtxMenu } from "./StageCtxMenu";

describe("ScaleBarCtxMenu — Copy Image entry", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    state.activeId = "img1";
    state.images = { img1: { kind: "image", pixel_size: null, pixel_unit: "px" } };
  });
  afterEach(() => vi.restoreAllMocks());

  it("renders 'Copy Image' as the top entry when an image is active", () => {
    render(<ScaleBarCtxMenu x={10} y={20} onClose={vi.fn()} />);
    const btn = screen.getByText("Copy Image");
    expect(btn).toBeInTheDocument();
    expect(btn).toHaveAttribute(
      "title",
      "Copy the image to the clipboard (includes on-screen annotations — see Preferences)",
    );
  });

  it("is absent when there is no active image", () => {
    state.activeId = null;
    render(<ScaleBarCtxMenu x={10} y={20} onClose={vi.fn()} />);
    expect(screen.queryByText("Copy Image")).toBeNull();
    // the rest of the menu (scale-bar toggle) still renders
    expect(screen.getByText("Hide Scale Bar")).toBeInTheDocument();
  });

  it("is absent for a spectrum (nothing to rasterize)", () => {
    state.images = { img1: { kind: "spectrum", pixel_size: null, pixel_unit: "px" } };
    render(<ScaleBarCtxMenu x={10} y={20} onClose={vi.fn()} />);
    expect(screen.queryByText("Copy Image")).toBeNull();
  });

  it("clicking triggers copyActive and closes the menu", async () => {
    const onClose = vi.fn();
    render(<ScaleBarCtxMenu x={10} y={20} onClose={onClose} />);
    fireEvent.click(screen.getByText("Copy Image"));

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(copyActive).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(state.setStatus).toHaveBeenCalledWith("copied to clipboard"),
    );
  });

  it("reports the clipboard error via setStatus when copyActive rejects", async () => {
    copyActive.mockImplementationOnce(() => Promise.reject(new Error("nope")));
    render(<ScaleBarCtxMenu x={10} y={20} onClose={vi.fn()} />);
    fireEvent.click(screen.getByText("Copy Image"));
    await waitFor(() =>
      expect(state.setStatus).toHaveBeenCalledWith("clipboard: nope"),
    );
  });
});
