import { fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import { integrateWindow } from "../../lib/eds/integrate";
import { makeRegion } from "../../lib/eds/regions";
import EdsIntegrationPanel from "./EdsIntegrationPanel";

const spec = {
  energy: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
  counts: [2, 3, 4, 10, 40, 12, 5, 4, 3, 2, 1],
  units: "keV",
};
const current = integrateWindow(spec, 4, 6, "linear")!;
const region = makeRegion(current, "Fe", "Sum spectrum");

type Props = ComponentProps<typeof EdsIntegrationPanel>;

function renderPanel(overrides: Partial<Props> = {}) {
  const props: Props = {
    current,
    element: "Fe",
    unit: "keV",
    source: "Sum spectrum",
    regions: [],
    onAdd: vi.fn(),
    onRemove: vi.fn(),
    onClear: vi.fn(),
    onSelect: vi.fn(),
    onExport: vi.fn(),
    ...overrides,
  };
  render(<EdsIntegrationPanel {...props} />);
  return props;
}

describe("EdsIntegrationPanel", () => {
  it("reports net ± σ, the window and the background for the live window", () => {
    renderPanel();
    const panel = screen.getByRole("region", { name: "Spectrum integration" });
    expect(panel).toHaveTextContent("Net 50 ± 8.43");
    expect(panel).toHaveTextContent("4.000–6.000 keV");
    expect(panel).toHaveTextContent("3 ch");
    expect(panel).toHaveTextContent("gross 62");
    expect(panel).toHaveTextContent("linear bg 12");
  });

  it("explains an empty window instead of showing a zero", () => {
    renderPanel({ current: null });
    expect(
      screen.getByText(/No channels in the current energy window/),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "+ Add region" })).toBeDisabled();
  });

  it("pins, restores and removes regions", () => {
    const props = renderPanel({ regions: [region] });

    fireEvent.click(screen.getByRole("button", { name: "+ Add region" }));
    expect(props.onAdd).toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Fe" }));
    expect(props.onSelect).toHaveBeenCalledWith(region);

    fireEvent.click(screen.getByRole("button", { name: "Remove region Fe" }));
    expect(props.onRemove).toHaveBeenCalledWith(region.id);
  });

  it("names an unnamed window by its energy range", () => {
    const custom = makeRegion(current, "(custom)", "ROI [0:4, 0:4]");
    expect(custom.label).toBe("4.00–6.00");
    renderPanel({ element: "(custom)", regions: [custom] });
    expect(screen.getByRole("button", { name: "4.00–6.00" })).toBeVisible();
  });
});
