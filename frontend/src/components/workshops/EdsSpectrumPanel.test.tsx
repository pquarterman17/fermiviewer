import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import EdsSpectrumPanel from "./EdsSpectrumPanel";

describe("EdsSpectrumPanel", () => {
  it("exposes spectrum source and display controls", () => {
    const onShowSum = vi.fn();
    const onToggleLive = vi.fn();
    const onShowPicker = vi.fn();
    const onToggleLog = vi.fn();
    const onToggleExpanded = vi.fn();
    render(
      <EdsSpectrumPanel
        source="sum"
        label="Sum spectrum"
        busy={false}
        liveActive={false}
        logScale={false}
        expanded={false}
        onShowSum={onShowSum}
        onToggleLive={onToggleLive}
        onShowPicker={onShowPicker}
        onToggleLog={onToggleLog}
        onToggleExpanded={onToggleExpanded}
      >
        <div>plot</div>
      </EdsSpectrumPanel>,
    );

    expect(screen.getByText("Sum spectrum")).toBeVisible();
    expect(screen.getByRole("button", { name: "Whole cube" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    fireEvent.click(screen.getByRole("button", { name: "Live stage pixel" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Preview pixel / ROI" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Log counts" }));
    fireEvent.click(screen.getByRole("button", { name: "Expand" }));
    expect(onToggleLive).toHaveBeenCalledOnce();
    expect(onShowPicker).toHaveBeenCalledOnce();
    expect(onToggleLog).toHaveBeenCalledOnce();
    expect(onToggleExpanded).toHaveBeenCalledOnce();
  });

  it("surfaces loading state without discarding the current plot", () => {
    render(
      <EdsSpectrumPanel
        source="picker"
        label="ROI [1:3, 2:4]"
        busy
        liveActive={false}
        logScale
        expanded
        onShowSum={() => {}}
        onToggleLive={() => {}}
        onShowPicker={() => {}}
        onToggleLog={() => {}}
        onToggleExpanded={() => {}}
      >
        <div>existing plot</div>
      </EdsSpectrumPanel>,
    );
    expect(screen.getByText("Loading…")).toBeVisible();
    expect(screen.getByText("existing plot")).toBeVisible();
    expect(screen.getByRole("button", { name: "Compact" })).toBeVisible();
  });
});
