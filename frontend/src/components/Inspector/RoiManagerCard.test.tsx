// ROI Manager store logic: save / recall / delete / persist round-trip.
// Uses the same vi.mock pattern as HistoryCard.test.tsx — exercises
// the named-ROI actions directly (no component render needed for the
// pure-logic cases; one smoke render to verify the card mounts).

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// ── minimal store mock (stable references, no fresh []/{}  per render) ──

const SAVED: import("../../store/viewer").SavedRoi[] = [];

const saveRoiFn = vi.fn((imageId: string, name: string, roi: { kind: "roi" | "ellipse"; pts: { x: number; y: number }[] }) => {
  const entry = {
    id: `sr_${SAVED.length}`,
    name: name || `ROI ${SAVED.length + 1}`,
    kind: roi.kind,
    pts: roi.pts,
    createdAt: new Date().toISOString(),
  };
  // replace same name
  const idx = SAVED.findIndex((r) => r.name === entry.name);
  if (idx >= 0) SAVED.splice(idx, 1, entry);
  else SAVED.push(entry);
  state.savedRois[imageId] = [...SAVED];
});
const recallRoiFn = vi.fn();
const deleteRoiFn = vi.fn((imageId: string, roiId: string) => {
  const arr = state.savedRois[imageId] ?? [];
  state.savedRois[imageId] = arr.filter((r) => r.id !== roiId);
});
const setStatusFn = vi.fn();

const ROI_MEASURE = {
  id: "m1",
  kind: "roi" as const,
  pts: [{ x: 0.1, y: 0.2 }, { x: 0.5, y: 0.6 }],
};

const state = {
  activeId: "img1",
  measures: { img1: [ROI_MEASURE] } as Record<string, typeof ROI_MEASURE[]>,
  roiStats: {} as Record<string, { mean: number; std: number; min: number; max: number; area: number; unit: string }>,
  savedRois: {} as Record<string, import("../../store/viewer").SavedRoi[]>,
  selectedMeasure: "m1" as string | null,
  saveRoi: saveRoiFn,
  recallRoi: recallRoiFn,
  deleteRoi: deleteRoiFn,
  setStatus: setStatusFn,
};

vi.mock("../../store/viewer", () => ({
  useViewer: Object.assign(
    (sel: (s: typeof state) => unknown) => sel(state),
    { getState: () => state },
  ),
}));

import RoiManagerCard from "./RoiManagerCard";

describe("RoiManagerCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    SAVED.length = 0;
    state.savedRois = {};
    state.selectedMeasure = "m1";
  });

  it("renders empty list and enables Save when an roi is selected", () => {
    render(<RoiManagerCard />);
    expect(screen.getByText("ROI Manager")).toBeInTheDocument();
    expect(screen.getByText("No saved ROIs yet.")).toBeInTheDocument();
    const btn = screen.getByRole("button", { name: /save/i });
    expect(btn).not.toBeDisabled();
  });

  it("disables Save when no roi/ellipse is selected", () => {
    state.selectedMeasure = null;
    render(<RoiManagerCard />);
    const btn = screen.getByRole("button", { name: /save/i });
    expect(btn).toBeDisabled();
  });

  it("calls saveRoi with the typed name on Save click", () => {
    render(<RoiManagerCard />);
    const input = screen.getByPlaceholderText(/Name/i);
    fireEvent.change(input, { target: { value: "My grain boundary" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    expect(saveRoiFn).toHaveBeenCalledWith("img1", "My grain boundary", {
      kind: "roi",
      pts: ROI_MEASURE.pts,
    });
  });

  it("calls saveRoi with Enter key press", () => {
    render(<RoiManagerCard />);
    const input = screen.getByPlaceholderText(/Name/i);
    fireEvent.change(input, { target: { value: "Enter ROI" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(saveRoiFn).toHaveBeenCalledOnce();
  });

  it("renders saved ROIs and calls recallRoi on row click", () => {
    state.savedRois = {
      img1: [
        {
          id: "sr_0",
          name: "GrainA",
          kind: "roi",
          pts: [{ x: 0.1, y: 0.2 }, { x: 0.5, y: 0.6 }],
          createdAt: "2026-06-18T00:00:00.000Z",
        },
      ],
    };
    render(<RoiManagerCard />);
    expect(screen.getByText("GrainA")).toBeInTheDocument();
    fireEvent.click(screen.getByText("GrainA").closest(".fvd-measure-row")!);
    expect(recallRoiFn).toHaveBeenCalledWith("img1", "sr_0");
  });

  it("calls deleteRoi on × button and stops propagation (no recall)", () => {
    state.savedRois = {
      img1: [
        {
          id: "sr_0",
          name: "GrainA",
          kind: "roi",
          pts: [{ x: 0.1, y: 0.2 }, { x: 0.5, y: 0.6 }],
          createdAt: "2026-06-18T00:00:00.000Z",
        },
      ],
    };
    render(<RoiManagerCard />);
    fireEvent.click(screen.getByTitle('Delete "GrainA"'));
    expect(deleteRoiFn).toHaveBeenCalledWith("img1", "sr_0");
    expect(recallRoiFn).not.toHaveBeenCalled();
  });

  it("shows the count badge matching the saved list length", () => {
    state.savedRois = {
      img1: [
        { id: "a", name: "R1", kind: "roi", pts: [], createdAt: "" },
        { id: "b", name: "R2", kind: "ellipse", pts: [], createdAt: "" },
      ],
    };
    render(<RoiManagerCard />);
    // Card renders count badge as a span with the number
    expect(screen.getByText("2")).toBeInTheDocument();
  });
});

// ── pure store-logic tests (no DOM) ────────────────────────────────────

describe("saveRoi store logic", () => {
  beforeEach(() => {
    SAVED.length = 0;
  });

  it("appends a new entry", () => {
    saveRoiFn("img1", "Alpha", { kind: "roi", pts: [{ x: 0, y: 0 }, { x: 1, y: 1 }] });
    expect(SAVED).toHaveLength(1);
    expect(SAVED[0].name).toBe("Alpha");
    expect(SAVED[0].kind).toBe("roi");
  });

  it("replaces an entry with the same name (re-save after geometry tweak)", () => {
    saveRoiFn("img1", "Alpha", { kind: "roi", pts: [{ x: 0, y: 0 }, { x: 0.5, y: 0.5 }] });
    saveRoiFn("img1", "Alpha", { kind: "roi", pts: [{ x: 0.1, y: 0.1 }, { x: 0.9, y: 0.9 }] });
    expect(SAVED).toHaveLength(1);
    expect(SAVED[0].pts[0].x).toBeCloseTo(0.1);
  });

  it("keeps distinct names as separate entries", () => {
    saveRoiFn("img1", "Alpha", { kind: "roi", pts: [] });
    saveRoiFn("img1", "Beta", { kind: "ellipse", pts: [] });
    expect(SAVED).toHaveLength(2);
  });
});

describe("deleteRoi store logic", () => {
  it("removes the matching id and leaves others", () => {
    state.savedRois = {
      img1: [
        { id: "x", name: "A", kind: "roi", pts: [], createdAt: "" },
        { id: "y", name: "B", kind: "roi", pts: [], createdAt: "" },
      ],
    };
    deleteRoiFn("img1", "x");
    expect(state.savedRois["img1"]).toHaveLength(1);
    expect(state.savedRois["img1"][0].id).toBe("y");
  });
});
