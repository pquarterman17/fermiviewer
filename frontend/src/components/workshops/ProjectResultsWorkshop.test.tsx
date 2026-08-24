import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import type { ImageMeta, PersistedResultRecord } from "../../lib/api";
import { useViewer } from "../../store/viewer";
import ProjectResultsWorkshop from "./ProjectResultsWorkshop";

const initialState = useViewer.getState();

function image(id: string): ImageMeta {
  return {
    id,
    name: `${id}.dm4`,
    kind: "spectrum_image",
    shape: [8, 8, 64],
    dtype: "float32",
    pixel_size: 1,
    pixel_unit: "nm",
    value_unit: "counts",
    n_channels: 64,
    energy_first: 0,
    energy_last: 20,
    energy_units: "keV",
    stage_tilt_deg: null,
    content_rows: null,
    meta: {},
  };
}

function result(id: string, sourceId: string, created: string): PersistedResultRecord {
  return {
    id,
    analysis: "eds.quantify",
    label: `Result ${id}`,
    created_at: created,
    status: "completed",
    source_ids: [sourceId],
    outputs: [{ kind: "scalar", name: "Fe", data: { value: 50, unit: "at%" } }],
  };
}

beforeEach(() => useViewer.setState(initialState, true));

describe("ProjectResultsWorkshop", () => {
  it("explains how saved results appear when the project has none", () => {
    render(<ProjectResultsWorkshop />);
    expect(screen.getByText("No saved results yet")).toBeVisible();
    expect(screen.getByText(/Run a supported analysis/)).toBeVisible();
    expect(screen.getByText(/reappear here when the project is reopened/)).toBeVisible();
  });

  it("sorts newest first and filters to the active image", () => {
    useViewer.setState({
      images: { a: image("a"), b: image("b") },
      order: ["a", "b"],
      activeId: "a",
      persistedResults: [
        result("old", "a", "2026-08-20T12:00:00Z"),
        result("new", "b", "2026-08-22T12:00:00Z"),
      ],
    });
    const { container } = render(<ProjectResultsWorkshop />);

    const headings = [...container.querySelectorAll(".fvd-result-title-block h3")];
    expect(headings.map((node) => node.textContent)).toEqual(["Result new", "Result old"]);

    fireEvent.click(screen.getByRole("button", { name: "Active image" }));
    expect(screen.getByText("Result old")).toBeVisible();
    expect(screen.queryByText("Result new")).toBeNull();
    expect(screen.getByText("1 shown")).toBeVisible();
  });

  it("matches the active image against derived outputs, not only sources", () => {
    // Inspecting an element map (a derived id) must surface the
    // quantification that produced it, not an empty filtered state.
    useViewer.setState({
      images: { a: image("a"), map: image("map") },
      order: ["a", "map"],
      activeId: "map",
      persistedResults: [
        { ...result("r1", "a", "2026-08-22T12:00:00Z"), derived_ids: ["map"] },
        result("r2", "elsewhere", "2026-08-21T12:00:00Z"),
      ],
    });
    render(<ProjectResultsWorkshop />);
    fireEvent.click(screen.getByRole("button", { name: "Active image" }));
    expect(screen.getByText("Result r1")).toBeVisible();
    expect(screen.queryByText("Result r2")).toBeNull();
  });

  it("keeps a deterministic order when a record carries an unparseable date", () => {
    useViewer.setState({
      images: { a: image("a") },
      order: ["a"],
      activeId: "a",
      persistedResults: [
        { ...result("weird", "a", "not-a-date") },
        result("dated", "a", "2026-08-22T12:00:00Z"),
      ],
    });
    const { container } = render(<ProjectResultsWorkshop />);
    const headings = [...container.querySelectorAll(".fvd-result-title-block h3")];
    // Unparseable pins to the epoch, so real timestamps sort ahead of it.
    expect(headings.map((node) => node.textContent)).toEqual(["Result dated", "Result weird"]);
  });

  it("selects an available source from a result card", () => {
    useViewer.setState({
      images: { a: image("a"), b: image("b") },
      order: ["a", "b"],
      activeId: "a",
      selected: ["a"],
      persistedResults: [result("r1", "b", "2026-08-22T12:00:00Z")],
    });
    render(<ProjectResultsWorkshop />);
    fireEvent.click(screen.getByRole("button", { name: "b.dm4" }));
    expect(useViewer.getState().activeId).toBe("b");
    expect(useViewer.getState().selected).toEqual(["b"]);
  });
});
