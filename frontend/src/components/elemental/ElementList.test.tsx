import { fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import type { IdentifiedElement } from "../../lib/elemental/identify";
import type { SpeciesRow } from "../../lib/elemental/speciesRows";
import { edsSpecies, eelsSpecies } from "../../lib/spectrum/species";
import EdsElementList from "./ElementList";

function evidenceFor(
  symbol: string,
  net: number,
  confidence: IdentifiedElement["confidence"],
): IdentifiedElement {
  return {
    symbol,
    transition: "K",
    energy: 1.74,
    windowLo: 1.655,
    windowHi: 1.825,
    net,
    sigma: net / 200,
    significance: 200,
    confidence,
    deltaKev: 0.002,
    relative: 1,
    recommended: confidence !== "trace",
  };
}

function row(
  symbol: string,
  net: number,
  confidence: IdentifiedElement["confidence"],
  visible = true,
): SpeciesRow {
  return {
    species: edsSpecies(symbol, "K", 1.74, { visible }),
    evidence: evidenceFor(symbol, net, confidence),
  };
}

type Props = ComponentProps<typeof EdsElementList>;

function renderList(overrides: Partial<Props> = {}) {
  const props: Props = {
    rows: [
      row("Si", 3_100_000, "strong"),
      row("Cu", 100_000, "trace", false),
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
    fireEvent.click(screen.getByRole("button", { name: /^Ta/ }));
    expect(props.onAdd).toHaveBeenCalledWith("Ta");
  });

  it("keeps a hand-added species that the last identification did not measure", () => {
    // Rows come from species, not evidence — an element nothing detected a
    // peak for still gets a row, it just has nothing to report in it.
    renderList({
      rows: [{ species: edsSpecies("Ta", "L", 8.146), evidence: null }],
    });
    expect(screen.getByLabelText("Show Ta")).toBeVisible();
    expect(screen.getByText("added")).toBeVisible();
    expect(screen.getByText("8.146")).toBeVisible();
  });

  it("toggles and removes by species id, not by symbol", () => {
    // Two rows can share an element on different transitions, so the symbol
    // is not a usable identifier here.
    const only = row("Si", 1000, "strong");
    const props = renderList({ rows: [only] });
    fireEvent.click(screen.getByLabelText("Show Si"));
    expect(props.onToggle).toHaveBeenCalledWith(only.species.id, false);
    fireEvent.click(screen.getByLabelText("Remove Si"));
    expect(props.onRemove).toHaveBeenCalledWith(only.species.id);
  });

  it("explains itself when nothing was identified", () => {
    renderList({ rows: [] });
    expect(screen.getByText(/No elements identified/)).toBeVisible();
  });

  it("shows the edge and eV energy for an EELS species, without the EDS alpha suffix", () => {
    // Item 6: the row must carry the EDGE, not just the element — Si K and
    // Si L23 are distinct rows for the same symbol, distinguished only by
    // this cell.
    renderList({
      rows: [{ species: eelsSpecies("Fe", "L23", 708), evidence: null }],
    });
    expect(screen.getByText("L23")).toBeVisible();
    expect(screen.queryByText("L23α")).toBeNull();
    expect(screen.getByText("708 eV")).toBeVisible();
  });
});
