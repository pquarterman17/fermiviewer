import { createRef } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type uPlot from "uplot";

import PlotContextSurface from "./PlotContextSurface";

function plotRef() {
  return {
    current: {
      data: [[1, 2, 3], [4, 5, 6]],
      series: [{ label: "x" }, { label: "y", stroke: "#3b82f6", width: 1.5, show: true }],
      scales: { x: { min: 1, max: 3 }, y: { min: 4, max: 6 } },
      axes: [{}, {}],
      root: document.createElement("div"),
      width: 300,
      height: 200,
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

  describe("vector + high-DPI export", () => {
    beforeEach(() => {
      globalThis.URL.createObjectURL = vi.fn(() => "blob:mock");
      globalThis.URL.revokeObjectURL = vi.fn();
      vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    });
    afterEach(() => vi.restoreAllMocks());

    it("offers SVG and both high-DPI PNG items alongside the relabelled screen PNG", () => {
      render(
        <PlotContextSurface
          ref={createRef()}
          plotRef={plotRef()}
          label="Test spectrum"
          filename="spectrum.png"
        />,
      );
      fireEvent.keyDown(screen.getByLabelText("Test spectrum plot"), { key: "ContextMenu" });

      expect(screen.getByRole("menuitem", { name: "Save plot PNG (screen)" })).toBeInTheDocument();
      expect(screen.getByRole("menuitem", { name: "Export SVG (vector)" })).toBeInTheDocument();
      expect(screen.getByRole("menuitem", { name: "Export PNG (300 dpi)" })).toBeInTheDocument();
      expect(screen.getByRole("menuitem", { name: "Export PNG (600 dpi)" })).toBeInTheDocument();
    });

    it("downloads an SVG whose content starts with <svg when Export SVG is clicked", () => {
      let capturedBlob: Blob | null = null;
      globalThis.URL.createObjectURL = vi.fn((b: Blob) => {
        capturedBlob = b;
        return "blob:mock";
      });

      render(
        <PlotContextSurface
          ref={createRef()}
          plotRef={plotRef()}
          label="Test spectrum"
          filename="spectrum.png"
        />,
      );
      fireEvent.keyDown(screen.getByLabelText("Test spectrum plot"), { key: "ContextMenu" });
      fireEvent.click(screen.getByRole("menuitem", { name: "Export SVG (vector)" }));

      expect(globalThis.URL.createObjectURL).toHaveBeenCalled();
      expect(capturedBlob).not.toBeNull();
      expect(capturedBlob!.type).toBe("image/svg+xml");
      return capturedBlob!.text().then((text) => {
        expect(text.startsWith("<svg")).toBe(true);
        expect(text).toContain("Test spectrum");
      });
    });

    it("names the SVG download by swapping the PNG extension", () => {
      let downloadName: string | null = null;
      vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(
        function (this: HTMLAnchorElement) {
          downloadName = this.download;
        },
      );

      render(
        <PlotContextSurface
          ref={createRef()}
          plotRef={plotRef()}
          label="Test spectrum"
          filename="eds-spectrum.png"
        />,
      );
      fireEvent.keyDown(screen.getByLabelText("Test spectrum plot"), { key: "ContextMenu" });
      fireEvent.click(screen.getByRole("menuitem", { name: "Export SVG (vector)" }));

      expect(downloadName).toBe("eds-spectrum.svg");
    });

    it("disables the vector/high-DPI items (but not the always-available screen PNG) when the plot ref is null", () => {
      render(
        <PlotContextSurface
          ref={createRef()}
          plotRef={{ current: null }}
          label="Test spectrum"
          filename="spectrum.png"
        />,
      );
      fireEvent.keyDown(screen.getByLabelText("Test spectrum plot"), { key: "ContextMenu" });

      expect(screen.getByRole("menuitem", { name: "Export SVG (vector)" })).toBeDisabled();
      expect(screen.getByRole("menuitem", { name: "Export PNG (300 dpi)" })).toBeDisabled();
      expect(screen.getByRole("menuitem", { name: "Export PNG (600 dpi)" })).toBeDisabled();
      expect(screen.getByRole("menuitem", { name: "Save plot PNG (screen)" })).not.toBeDisabled();
    });

    it("a disabled export item does not fire its handler even if clicked directly", () => {
      let called = false;
      globalThis.URL.createObjectURL = vi.fn(() => {
        called = true;
        return "blob:mock";
      });
      render(
        <PlotContextSurface
          ref={createRef()}
          plotRef={{ current: null }}
          label="Test spectrum"
          filename="spectrum.png"
        />,
      );
      fireEvent.keyDown(screen.getByLabelText("Test spectrum plot"), { key: "ContextMenu" });
      fireEvent.click(screen.getByRole("menuitem", { name: "Export SVG (vector)" }));
      expect(called).toBe(false);
    });
  });
});
