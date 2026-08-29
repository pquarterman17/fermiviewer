// RegionsCard — the CSV-export deliverable of plan item 15, plus the
// SHAPE_ANALYSIS_PLAN.md Wave-2 #5 circle/ellipse "Fit" action. Uses the
// same store-mock pattern as RoiManagerCard.test.tsx (stable references,
// no fresh []/{} per render).

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const proposeRegionMock = vi.fn();
const fitShapeMock = vi.fn();
vi.mock("../../lib/api/regions", () => ({
  proposeRegion: (...args: unknown[]) => proposeRegionMock(...args),
  fitShape: (...args: unknown[]) => fitShapeMock(...args),
}));

type RegionMeasure = {
  id: string;
  kind: string;
  pts: { x: number; y: number }[];
  text?: string;
  displayUnit?: "auto" | "A" | "nm" | "um" | "mm";
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
    expect(screen.getByText("Region Measurements")).toBeInTheDocument();
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

  it("honors the measure's displayUnit override in the area column (measure display-units feature)", () => {
    state.measures = { img1: [{ ...POLYGON, displayUnit: "um" }] };
    render(<RegionsCard />);
    // 20000 nm^2 -> 0.02 um^2 (squared factor 1e6, not the linear 1e3)
    expect(screen.getByText("0.02 µm²")).toBeInTheDocument();
    expect(screen.queryByText("20000 nm²")).toBeNull();
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

    it("stays in the image's calibration unit regardless of any per-measure override — the column header names ONE unit for the whole table", () => {
      state.measures = { img1: [{ ...POLYGON, displayUnit: "um" }] };
      let capturedBlob: Blob | null = null;
      globalThis.URL.createObjectURL = vi.fn((b: Blob) => {
        capturedBlob = b;
        return "blob:mock";
      });
      render(<RegionsCard />);
      fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
      return capturedBlob!.text().then((text) => {
        expect(text).toContain("area_nm2");
        expect(text).toContain("Grain A,polygon,5000,20000");
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

  describe("Fit (SHAPE_ANALYSIS_PLAN.md Wave-2 #5)", () => {
    // 5 vertices (the ellipse minimum) at normalized quarter-turn
    // positions — x != y at every vertex and the image is non-square
    // (shape [50, 100]), so a row/col swap or a 0-vs-1-based slip in the
    // conversion is visible in every coordinate, not just accidentally
    // masked by symmetry.
    const PENTAGON: RegionMeasure = {
      id: "m1",
      kind: "polygon",
      text: "Grain A",
      pts: [
        { x: 0, y: 0 },
        { x: 0.5, y: 0 },
        { x: 1, y: 0.5 },
        { x: 0.5, y: 1 },
        { x: 0, y: 0.5 },
      ],
    };

    beforeEach(() => {
      proposeRegionMock.mockReset();
      fitShapeMock.mockReset();
    });

    it("converts normalized {x,y} vertices to 1-based [row, col] wire points (pins the verified basing)", async () => {
      state.measures = { img1: [PENTAGON] };
      fitShapeMock.mockResolvedValue({
        circle: { cy: 26, cx: 51, r: 25, rms: 1 },
        ellipse: { cy: 26, cx: 51, a: 25, b: 24, theta_rad: 0, rms: 1 },
      });
      render(<RegionsCard />);
      fireEvent.click(screen.getByRole("button", { name: "Fit" }));
      await waitFor(() => expect(fitShapeMock).toHaveBeenCalledOnce());
      // shape [50, 100] -> h=50, w=100; row = y*50+1, col = x*100+1
      expect(fitShapeMock).toHaveBeenCalledWith({
        points: [
          [1, 1],
          [1, 51],
          [26, 101],
          [51, 51],
          [26, 1],
        ],
      });
    });

    it("converts the wire's theta_rad to degrees for display, stating the axis convention", async () => {
      state.measures = { img1: [PENTAGON] };
      fitShapeMock.mockResolvedValue({
        circle: { cy: 1, cx: 1, r: 1, rms: 0.1 },
        ellipse: { cy: 1, cx: 1, a: 2, b: 1, theta_rad: Math.PI / 6, rms: 0.1 },
      });
      render(<RegionsCard />);
      fireEvent.click(screen.getByRole("button", { name: "Fit" }));
      const ellipseLine = await screen.findByTitle(/θ measured from the image/);
      const match = ellipseLine.textContent?.match(/θ (-?[\d.]+)°/);
      expect(match).not.toBeNull();
      expect(Number(match![1])).toBeCloseTo(30, 3); // pi/6 rad = 30 deg
    });

    it("shows fit lengths calibrated when the image has a pixel size", async () => {
      state.measures = { img1: [PENTAGON] }; // IMG_META: pixel_size 2, unit nm
      fitShapeMock.mockResolvedValue({
        circle: { cy: 1, cx: 1, r: 10, rms: 0.5 },
        ellipse: { cy: 1, cx: 1, a: 10, b: 8, theta_rad: 0, rms: 0.5 },
      });
      render(<RegionsCard />);
      fireEvent.click(screen.getByRole("button", { name: "Fit" }));
      const circleLine = await screen.findByText(/^circle — center/);
      // r=10px * pixel_size 2nm/px = 20nm; rms=0.5px * 2 = 1nm
      expect(circleLine.textContent).toContain("r 20 nm");
      expect(circleLine.textContent).toContain("rms 1 nm");
    });

    it("falls back to px display when the image is uncalibrated", async () => {
      state.images = { img1: { ...IMG_META, pixel_size: null } };
      state.measures = { img1: [PENTAGON] };
      fitShapeMock.mockResolvedValue({
        circle: { cy: 1, cx: 1, r: 10, rms: 0.5 },
        ellipse: { cy: 1, cx: 1, a: 10, b: 8, theta_rad: 0, rms: 0.5 },
      });
      render(<RegionsCard />);
      fireEvent.click(screen.getByRole("button", { name: "Fit" }));
      const circleLine = await screen.findByText(/^circle — center/);
      expect(circleLine.textContent).toContain("r 10 px");
      expect(circleLine.textContent).not.toContain("nm");
    });

    it("disables Fit below the 5-vertex minimum with an explanatory title", () => {
      state.measures = { img1: [POLYGON] }; // 4 vertices
      render(<RegionsCard />);
      const btn = screen.getByRole("button", { name: "Fit" });
      expect(btn).toBeDisabled();
      expect(btn.title).toMatch(/needs ≥ 5 vertices/);
      expect(fitShapeMock).not.toHaveBeenCalled();
    });

    it("surfaces a fit-shape failure (e.g. the ellipse-minimum 422) via setStatus", async () => {
      state.measures = { img1: [PENTAGON] };
      fitShapeMock.mockRejectedValue(
        new Error("need >= 5 non-degenerate (row, col) points to fit an ellipse"),
      );
      render(<RegionsCard />);
      fireEvent.click(screen.getByRole("button", { name: "Fit" }));
      await waitFor(() =>
        expect(setStatusFn).toHaveBeenCalledWith(
          "fit shape failed: need >= 5 non-degenerate (row, col) points to fit an ellipse",
        ),
      );
    });
  });
});
