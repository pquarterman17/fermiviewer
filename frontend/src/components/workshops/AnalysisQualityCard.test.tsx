import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { GrainResult } from "../../lib/api";
import { AnalysisQualityCard, grainMeanDiameter } from "./AnalysisQualityCard";

describe("AnalysisQualityCard", () => {
  it("explains a poor result and requires explicit acceptance", () => {
    const accept = vi.fn();
    render(<AnalysisQualityCard
      value={{
        rating: "poor",
        summary: "Likely failure",
        concerns: [{
          rating: "poor",
          message: "Too many fragments.",
          suggestion: "Increase minimum area.",
        }],
      }}
      accepted={false}
      onAccept={accept}
    />);
    expect(screen.getByRole("alert")).toHaveTextContent("Too many fragments");
    fireEvent.click(screen.getByText("Use anyway"));
    expect(accept).toHaveBeenCalledOnce();
  });

  it("labels accepted poor output as unvalidated", () => {
    render(<AnalysisQualityCard
      value={{ rating: "poor", summary: "Likely failure", concerns: [] }}
      accepted
      onAccept={() => undefined}
    />);
    expect(screen.getByText(/not validated/)).toBeInTheDocument();
    expect(screen.queryByText("Use anyway")).toBeNull();
  });
});

describe("grainMeanDiameter", () => {
  const base = { mean_diameter_px: 10, equiv_diameter_px: [8, 12], unit: "nm" };
  it("matches the histogram's calibrated unit", () => {
    const r = { ...base, diameter_calibrated: [4, 6] } as unknown as GrainResult;
    expect(grainMeanDiameter(r)).toBe("5 nm");
  });
  it("falls back to px when any grain is uncalibrated", () => {
    const r = { ...base, diameter_calibrated: [4, null] } as unknown as GrainResult;
    expect(grainMeanDiameter(r)).toBe("10.0 px");
  });
});
