// RegionsCard — the CSV-export deliverable of plan item 15. Uses the
// same store-mock pattern as RoiManagerCard.test.tsx (stable references,
// no fresh []/{} per render).

import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type RegionMeasure = {
  id: string;
  kind: string;
  pts: { x: number; y: number }[];
  text?: string;
};

const POLYGON: RegionMeasure = {
  id: "m1",
  kind: "polygon",
  text: "Grain A",
  pts: [
    { x: 0, y: 0 },
    { x: 1, y: 0 },
    { x: 1, y: 1 },
    { x: 0, y: 1 },
  ],
};

const IMG_META = {
  id: "img1",
  name: "sample.tif",
  kind: "image" as const,
  shape: [50, 100],
  pixel_size: 2 as number | null,
  pixel_unit: "nm",
};

const setStatusFn = vi.fn();

const state = {
  activeId: "img1",
  images: { img1: IMG_META } as Record<string, typeof IMG_META>,
  measures: { img1: [] as RegionMeasure[] },
  setStatus: setStatusFn,
};

vi.mock("../../store/viewer", () => ({
  useViewer: Object.assign(
    (sel: (s: typeof state) => unknown) => sel(state),
    { getState: () => state },
  ),
}));

import RegionsCard from "./RegionsCard";

describe("RegionsCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    state.activeId = "img1";
    state.images = { img1: IMG_META };
    state.measures = { img1: [] };
  });

  it("renders nothing when there is no active image", () => {
    state.activeId = null as unknown as string;
    const { container } = render(<RegionsCard />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the empty-state note when the image has no regions", () => {
    render(<RegionsCard />);
    expect(screen.getByText("Regions")).toBeInTheDocument();
    expect(
      screen.getByText(/No regions drawn yet/),
    ).toBeInTheDocument();
  });

  it("lists a region row with physical area + unit when calibrated", () => {
    state.measures = { img1: [POLYGON] };
    render(<RegionsCard />);
    expect(screen.getByText("Grain A")).toBeInTheDocument();
    // area = 100*50 px^2 * 2^2 nm^2/px^2 = 20000 nm^2
    expect(screen.getByText("20000 nm²")).toBeInTheDocument();
  });

  it("falls back to px² display when the image is uncalibrated", () => {
    state.images = { img1: { ...IMG_META, pixel_size: null } };
    state.measures = { img1: [POLYGON] };
    render(<RegionsCard />);
    expect(screen.getByText("5000 px²")).toBeInTheDocument();
  });

  it("shows the region count badge", () => {
    state.measures = { img1: [POLYGON, { ...POLYGON, id: "m2", text: undefined }] };
    render(<RegionsCard />);
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("Region 2")).toBeInTheDocument();
  });

  describe("Export CSV", () => {
    beforeEach(() => {
      globalThis.URL.createObjectURL = vi.fn(() => "blob:mock");
      globalThis.URL.revokeObjectURL = vi.fn();
      vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    });
    afterEach(() => vi.restoreAllMocks());

    it("downloads a CSV whose header states the real unit and rows carry the region", () => {
      state.measures = { img1: [POLYGON] };
      let capturedBlob: Blob | null = null;
      globalThis.URL.createObjectURL = vi.fn((b: Blob) => {
        capturedBlob = b;
        return "blob:mock";
      });
      render(<RegionsCard />);
      fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
      expect(globalThis.URL.createObjectURL).toHaveBeenCalled();
      expect(capturedBlob).not.toBeNull();
      return capturedBlob!.text().then((text) => {
        expect(text).toContain("# image: sample.tif");
        expect(text).toContain("area_nm2");
        expect(text).toContain("Grain A,polygon,5000,20000");
      });
    });

    it("uncalibrated export states area_physical and leaves the cell empty, not 0", () => {
      state.images = { img1: { ...IMG_META, pixel_size: null } };
      state.measures = { img1: [POLYGON] };
      let capturedBlob: Blob | null = null;
      globalThis.URL.createObjectURL = vi.fn((b: Blob) => {
        capturedBlob = b;
        return "blob:mock";
      });
      render(<RegionsCard />);
      fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
      return capturedBlob!.text().then((text) => {
        expect(text).toContain("area_physical");
        // area_px2=5000 then an EMPTY physical cell (no fabricated 0/NaN),
        // then perimeter — i.e. two consecutive commas.
        expect(text).toContain("Grain A,polygon,5000,,300");
      });
    });

    it("reports the exported count via setStatus", () => {
      state.measures = { img1: [POLYGON] };
      render(<RegionsCard />);
      fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
      expect(setStatusFn).toHaveBeenCalledWith("exported 1 region(s) to CSV");
    });
  });

  describe("Copy CSV", () => {
    afterEach(() => {
      vi.restoreAllMocks();
      Object.defineProperty(navigator, "clipboard", {
        value: undefined,
        configurable: true,
      });
    });

    it("copies CSV text via navigator.clipboard when available", async () => {
      const writeText = vi.fn().mockResolvedValue(undefined);
      Object.defineProperty(navigator, "clipboard", {
        value: { writeText },
        configurable: true,
      });
      state.measures = { img1: [POLYGON] };
      render(<RegionsCard />);
      fireEvent.click(screen.getByRole("button", { name: "Copy CSV" }));
      expect(writeText).toHaveBeenCalledOnce();
      const csv = writeText.mock.calls[0][0] as string;
      expect(csv).toContain("area_nm2");
      await Promise.resolve(); // flush the .then()
      expect(setStatusFn).toHaveBeenCalledWith("copied 1 region(s) as CSV");
    });

    it("falls back to a status message when clipboard is unavailable", () => {
      Object.defineProperty(navigator, "clipboard", {
        value: undefined,
        configurable: true,
      });
      state.measures = { img1: [POLYGON] };
      render(<RegionsCard />);
      fireEvent.click(screen.getByRole("button", { name: "Copy CSV" }));
      expect(setStatusFn).toHaveBeenCalledWith(
        "clipboard unavailable — use Export CSV instead",
      );
    });
  });
});
