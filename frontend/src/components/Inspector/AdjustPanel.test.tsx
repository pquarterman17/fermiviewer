// AdjustPanel "↺ Opened" reset-all-corrections button (WS5a): reverts the
// display to the seeded Opened history snapshot and disables itself once
// there is nothing to revert.

import { fireEvent, render, screen } from "@testing-library/react";
import { act } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ImageMeta } from "../../lib/api";
import { useViewer } from "../../store/viewer";
import AdjustPanel from "./AdjustPanel";

vi.mock("../../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../lib/api")>()),
  fetchHistogram: vi.fn().mockResolvedValue({ bins: [0, 1], counts: [1, 1] }),
}));

const image = {
  id: "a",
  name: "a.tif",
  kind: "image",
  shape: [10, 10],
  dtype: "uint8",
  pixel_size: null,
  pixel_unit: "",
  value_unit: "",
  meta: {},
} as ImageMeta;

beforeEach(() => {
  localStorage.setItem("fv_cards_v2", JSON.stringify({ Adjust: true }));
  useViewer.setState({
    images: {},
    order: [],
    activeId: null,
    display: {},
    history: {},
    historyAt: {},
  });
  useViewer.getState().ingest([image]);
});

describe("AdjustPanel reset corrections (WS5a)", () => {
  it("is disabled at the Opened step and reverts corrections when clicked", () => {
    render(<AdjustPanel />);
    const btn = screen.getByRole("button", { name: /Opened/ });
    expect(btn).toBeDisabled(); // freshly opened image — nothing to reset

    act(() => {
      useViewer.getState().setDisplay("a", { gamma: 0.5 });
      useViewer.getState().setDisplay("a", { invert: true });
    });
    expect(btn).toBeEnabled();

    fireEvent.click(btn);
    const s = useViewer.getState();
    expect(s.historyAt["a"]).toBe(0);
    expect(s.display["a"].gamma).toBe(1);
    expect(s.display["a"].invert).toBe(false);
    expect(btn).toBeDisabled(); // back at Opened
  });
});
