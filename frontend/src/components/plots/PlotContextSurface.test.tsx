import { createRef } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type uPlot from "uplot";

import PlotContextSurface from "./PlotContextSurface";

function plotRef() {
  return {
    current: {
      data: [[1, 2, 3], [4, 5, 6]],
      setScale: vi.fn(),
    } as unknown as uPlot,
  };
}

describe("PlotContextSurface", () => {
  it("opens from the context-menu key and resets the full x range", () => {
    const plot = plotRef();
    render(
      <PlotContextSurface
        ref={createRef()}
        plotRef={plot}
        label="Test spectrum"
        filename="test.png"
      />,
    );

    const surface = screen.getByLabelText("Test spectrum plot");
    fireEvent.keyDown(surface, { key: "ContextMenu" });
    fireEvent.click(screen.getByRole("menuitem", { name: "Reset view" }));

    expect(plot.current.setScale).toHaveBeenCalledWith("x", {
      min: 1,
      max: 3,
    });
  });

  it("supports menu arrow keys and optional data export", () => {
    const onExportData = vi.fn();
    render(
      <PlotContextSurface
        ref={createRef()}
        plotRef={plotRef()}
        label="Test map profile"
        filename="test.png"
        onExportData={onExportData}
        exportLabel="Export profile CSV"
      />,
    );

    fireEvent.contextMenu(screen.getByLabelText("Test map profile plot"), {
      clientX: 120,
      clientY: 80,
    });
    const reset = screen.getByRole("menuitem", { name: "Reset view" });
    reset.focus();
    fireEvent.keyDown(reset, { key: "End" });
    const exportItem = screen.getByRole("menuitem", {
      name: "Export profile CSV",
    });
    expect(exportItem).toHaveFocus();
    fireEvent.click(exportItem);
    expect(onExportData).toHaveBeenCalledOnce();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});
