import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AnalysisQualityCard } from "./AnalysisQualityCard";

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
