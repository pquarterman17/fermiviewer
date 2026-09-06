import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ImageMeta } from "../../lib/api";
import { useViewer, type Measure } from "../../store/viewer";

const applyCalibrationAxesMock = vi.fn();
const clearCalibrationMock = vi.fn();

vi.mock("../../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../lib/api")>()),
  applyCalibrationAxes: (...args: unknown[]) => applyCalibrationAxesMock(...args),
  clearCalibration: (...args: unknown[]) => clearCalibrationMock(...args),
}));

import CalibrationCard from "./CalibrationCard";

const image: ImageMeta = {
  id: "img",
  name: "afm.spm",
  kind: "image",
  shape: [100, 200],
  dtype: "float32",
  pixel_size: 2,
  pixel_spacing: [0.5, 2],
  pixel_unit: "nm",
  value_unit: "",
  n_channels: null,
  energy_first: null,
  energy_last: null,
  energy_units: "",
  stage_tilt_deg: null,
  meta: {},
};

const horizontal: Measure = {
  id: "line",
  kind: "distance",
  pts: [{ x: 0.1, y: 0.5 }, { x: 0.6, y: 0.5 }],
};

function seed(measure: Measure | null = null) {
  useViewer.setState(useViewer.getInitialState(), true);
  useViewer.setState({
    images: { img: image },
    order: ["img"],
    activeId: "img",
    measures: measure ? { img: [measure] } : {},
    selectedMeasure: measure?.id ?? null,
  });
}

describe("CalibrationCard per-axis editing", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    seed();
    applyCalibrationAxesMock.mockResolvedValue({ image });
  });

  it("makes anisotropy visible before editing", () => {
    render(<CalibrationCard />);
    expect(screen.getByRole("status")).toHaveTextContent("Rows 0.5");
    expect(screen.getByRole("status")).toHaveTextContent("Columns 2");
  });

  it("sends an equal pair when square mode is chosen on anisotropic data", async () => {
    seed(horizontal);
    render(<CalibrationCard />);
    fireEvent.change(screen.getByPlaceholderText("e.g. 200"), {
      target: { value: "400" },
    });
    expect(screen.getByText(/4.000 nm\/px on both axes/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Calibrate from line" }));
    await waitFor(() =>
      expect(applyCalibrationAxesMock).toHaveBeenCalledWith(
        "img", [4, 4], "nm",
      ),
    );
  });

  it("applies independently edited row and column extents", async () => {
    render(<CalibrationCard />);
    fireEvent.click(screen.getByRole("button", { name: "Per axis" }));
    const row = await screen.findByRole("spinbutton", { name: "Row pixel extent" });
    const col = screen.getByRole("spinbutton", { name: "Column pixel extent" });
    fireEvent.change(row, { target: { value: "0.75" } });
    fireEvent.change(col, { target: { value: "2.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply extents" }));
    await waitFor(() =>
      expect(applyCalibrationAxesMock).toHaveBeenCalledWith(
        "img", [0.75, 2.5], "nm",
      ),
    );
  });

  it("normalizes parser-style um without reinterpreting its values as nm", async () => {
    useViewer.setState({
      images: { img: { ...image, pixel_unit: "um" } },
    });
    render(<CalibrationCard />);
    fireEvent.click(screen.getByRole("button", { name: "Per axis" }));
    expect(screen.getByRole("combobox", { name: "Pixel extent unit" })).toHaveValue("µm");
    fireEvent.click(screen.getByRole("button", { name: "Apply extents" }));
    await waitFor(() =>
      expect(applyCalibrationAxesMock).toHaveBeenCalledWith(
        "img", [0.5, 2], "µm",
      ),
    );
  });

  it("converts both drafts when the unit changes", async () => {
    render(<CalibrationCard />);
    fireEvent.click(screen.getByRole("button", { name: "Per axis" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Pixel extent unit" }), {
      target: { value: "µm" },
    });
    expect(screen.getByRole("spinbutton", { name: "Row pixel extent" })).toHaveValue(0.0005);
    expect(screen.getByRole("spinbutton", { name: "Column pixel extent" })).toHaveValue(0.002);
    fireEvent.click(screen.getByRole("button", { name: "Apply extents" }));
    await waitFor(() =>
      expect(applyCalibrationAxesMock).toHaveBeenCalledWith(
        "img", [0.0005, 0.002], "µm",
      ),
    );
  });

  it("does not populate editable drafts under a guessed unit", async () => {
    useViewer.setState({
      images: { img: { ...image, pixel_unit: "m" } },
    });
    render(<CalibrationCard />);
    fireEvent.click(screen.getByRole("button", { name: "Per axis" }));
    expect(screen.getByRole("spinbutton", { name: "Row pixel extent" })).toHaveValue(null);
    expect(screen.getByRole("spinbutton", { name: "Column pixel extent" })).toHaveValue(null);
    expect(screen.getByRole("button", { name: "Apply extents" })).toBeDisabled();
  });

  it("uses a horizontal line for columns and preserves the row extent", async () => {
    seed(horizontal);
    render(<CalibrationCard />);
    fireEvent.click(screen.getByRole("button", { name: "Per axis" }));
    fireEvent.change(screen.getByPlaceholderText("e.g. 200"), {
      target: { value: "300" },
    });
    expect(screen.getByText(/column extent 3 nm\/px; other axis unchanged/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Calibrate column from line" }));
    await waitFor(() =>
      expect(applyCalibrationAxesMock).toHaveBeenCalledWith(
        "img", [0.5, 3], "nm",
      ),
    );
  });

  it("refuses a diagonal line with an actionable explanation", () => {
    seed({ ...horizontal, pts: [{ x: 0.1, y: 0.1 }, { x: 0.6, y: 0.6 }] });
    render(<CalibrationCard />);
    fireEvent.click(screen.getByRole("button", { name: "Per axis" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "horizontal or vertical line",
    );
    expect(screen.getByRole("button", { name: "Calibrate axis from line" })).toBeDisabled();
  });

  it("explains why one line cannot finish an uncalibrated per-axis pair", () => {
    seed(horizontal);
    useViewer.setState({
      images: {
        img: { ...image, pixel_size: null, pixel_spacing: null, pixel_unit: "" },
      },
    });
    render(<CalibrationCard />);
    fireEvent.click(screen.getByRole("button", { name: "Per axis" }));
    fireEvent.change(screen.getByPlaceholderText("e.g. 200"), {
      target: { value: "300" },
    });
    expect(screen.getByRole("status")).toHaveTextContent(
      "Enter the other axis extent",
    );
  });
});
