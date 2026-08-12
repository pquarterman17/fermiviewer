import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { EdsPeakfitResult } from "../../lib/api";
import { useViewer } from "../../store/viewer";

// Real uPlot needs a 2-D canvas context jsdom does not implement; stub it
// the same way SpectrumPlot.test.tsx does (lives in vi.hoisted() because
// vi.mock's factory is lifted above every top-level binding in the file),
// since only the readout text is under test here — not the plot's
// internal drawing.
const MockUplot = vi.hoisted(
  () =>
    class {
      constructor(_options: unknown, _data: unknown, host: HTMLElement) {
        host.appendChild(document.createElement("canvas"));
      }
      destroy() {}
      setSize() {}
    },
);
vi.mock("uplot", () => ({ default: MockUplot }));

vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return { ...actual, edsPeakfit: vi.fn() };
});

// mock the download seam the "Export fit report (CSV)" / "Export CSV"
// buttons use — same module every other workshop's CSV export mocks
vi.mock("../../lib/eelsQuantCsv", async (importActual) => {
  const actual =
    await importActual<typeof import("../../lib/eelsQuantCsv")>();
  return { ...actual, downloadCsv: vi.fn() };
});

import { edsPeakfit } from "../../lib/api";
import { downloadCsv } from "../../lib/eelsQuantCsv";
import EdsModelFit from "./EdsModelFit";

const RESULT: EdsPeakfitResult = {
  energy: [0, 0.02, 0.04],
  spectrum: [10, 20, 30],
  model: [9, 19, 31],
  elements: [
    {
      symbol: "Fe",
      line: "Ka",
      energy_kev: 6.404,
      net_area: 4000,
      net_area_error: 12.3,
      curve: [1, 2, 3],
    },
  ],
  reduced_chi2: 1.234,
  r_squared: 0.987,
  success: true,
};

afterEach(() => {
  vi.clearAllMocks();
  useViewer.setState({
    images: {},
    order: [],
    activeId: null,
    selected: [],
    savedRois: {},
    measures: {},
  });
});

describe("EdsModelFit", () => {
  it("renders the χ²ᵣ / R² readout from a peakfit response", async () => {
    vi.mocked(edsPeakfit).mockResolvedValue(RESULT);
    render(<EdsModelFit activeId="img1" elements="Fe" />);

    fireEvent.click(screen.getByRole("button", { name: "Deconvolve peaks" }));
    await waitFor(() => expect(edsPeakfit).toHaveBeenCalled());

    expect(await screen.findByText(/R² 0\.987/)).toBeInTheDocument();
    expect(screen.getByText(/χ²ᵣ 1\.23e\+0/)).toBeInTheDocument();
  });

  it("flags a non-converged fit in the same readout", async () => {
    vi.mocked(edsPeakfit).mockResolvedValue({ ...RESULT, success: false });
    render(<EdsModelFit activeId="img1" elements="Fe" />);

    fireEvent.click(screen.getByRole("button", { name: "Deconvolve peaks" }));
    await waitFor(() => expect(edsPeakfit).toHaveBeenCalled());

    expect(await screen.findByText(/not converged/)).toBeInTheDocument();
  });

  it("has no fit-report export button before a fit is run", () => {
    render(<EdsModelFit activeId="img1" elements="Fe" />);
    expect(
      screen.queryByRole("button", { name: "Export fit report (CSV)" }),
    ).not.toBeInTheDocument();
  });

  it("downloads a fit report CSV after a peakfit (#7)", async () => {
    vi.mocked(edsPeakfit).mockResolvedValue(RESULT);
    render(<EdsModelFit activeId="img1" elements="Fe" />);

    fireEvent.click(screen.getByRole("button", { name: "Deconvolve peaks" }));
    await waitFor(() => expect(edsPeakfit).toHaveBeenCalled());

    fireEvent.click(
      await screen.findByRole("button", { name: "Export fit report (CSV)" }),
    );
    expect(downloadCsv).toHaveBeenCalledOnce();
    const [filename, csv] = vi.mocked(downloadCsv).mock.calls[0];
    expect(filename).toBe("image_eds_fit_report.csv");
    expect(csv).toContain("# fermiviewer EDS fit report");
    expect(csv).toContain("Fe,Ka,6.404,4000,12.3,,,,");
  });
});
