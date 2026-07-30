import { fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import type { IdentifiedElement } from "../../lib/elemental/identify";
import EdsElementList from "./ElementList";

function element(
  symbol: string,
  net: number,
  confidence: IdentifiedElement["confidence"],
  selected = true,
): IdentifiedElement {
  return {
    symbol,
    line: "K",
    energyKev: 1.74,
    eLo: 1.655,
    eHi: 1.825,
    net,
    sigma: net / 200,
    significance: 200,
    confidence,
    deltaKev: 0.002,
    relative: 1,
    selected,
  };
}

type Props = ComponentProps<typeof EdsElementList>;

function renderList(overrides: Partial<Props> = {}) {
  const props: Props = {
    elements: [
      element("Si", 3_100_000, "strong"),
      element("Cu", 100_000, "trace", false),
    ],
    busy: false,
    onToggle: vi.fn(),
    onSetAll: vi.fn(),
    onReidentify: vi.fn(),
    onAdd: vi.fn(),
    onRemove: vi.fn(),
    onHover: vi.fn(),
    onFocus: vi.fn(),
    ...overrides,
  };
  render(<EdsElementList {...props} />);
  return props;
}

describe("EdsElementList", () => {
  it("summarises how many elements were found and how many are shown", () => {
    renderList();
    expect(screen.getByText("2 found · 1 shown")).toBeVisible();
  });

  it("ticks confident elements and leaves trace ones present but unticked", () => {
    renderList();
    expect(screen.getByLabelText("Show Si")).toBeChecked();
    const trace = screen.getByLabelText("Show Cu");
    expect(trace).not.toBeChecked();
    expect(trace).toBeVisible(); // reachable, not hidden
    expect(screen.getByText("trace?")).toBeVisible();
  });

  it("reports hover so the spectrum can highlight that element's peak", () => {
    const props = renderList();
    fireEvent.mouseEnter(screen.getByLabelText("Show Si").closest("li")!);
    expect(props.onHover).toHaveBeenCalledWith("Si");
  });

  it("shows at% instead of net counts once quantified", () => {
    renderList({ quantBySymbol: { Si: 33.25, Cu: 0.4 } });
    expect(screen.getByText("33.3 at%")).toBeVisible();
    expect(screen.queryByText("3.1M")).toBeNull();
  });

  it("offers the periodic table for an element the identifier missed", () => {
    const props = renderList();
    fireEvent.click(screen.getByRole("button", { name: "+ Add" }));
    fireEvent.click(screen.getByRole("button", { name: "Ta" }));
    expect(props.onAdd).toHaveBeenCalledWith("Ta");
  });

  it("explains itself when nothing was identified", () => {
    renderList({ elements: [] });
    expect(screen.getByText(/No elements identified/)).toBeVisible();
  });
});
