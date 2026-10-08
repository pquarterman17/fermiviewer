// AdjustPanel "↺ Opened" reset-all-corrections button (WS5a): reverts the
// display to the seeded Opened history snapshot and disables itself once
// there is nothing to revert.

import { fireEvent, render, screen } from "@testing-library/react";
import { act } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ImageMeta } from "../../lib/api";
import { useStageInfo } from "../../store/stage";
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

describe("AdjustPanel for colour composites (ADR 0003)", () => {
  it("replaces the controls with an explanation — colour has no window", () => {
    const rgb = {
      ...image,
      id: "c",
      name: "Composite — Fe, Cu",
      kind: "rgb_image",
      shape: [10, 10, 3],
    } as ImageMeta;
    act(() => {
      useViewer.getState().ingest([rgb]);
      useViewer.setState({ activeId: "c" });
    });
    render(<AdjustPanel />);
    expect(screen.getByText(/Colour composite/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Auto/ })).toBeNull();
  });
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

describe("AdjustPanel colour-range + tick validation", () => {
  beforeEach(() => {
    useStageInfo.setState({
      raster: { data: new Uint16Array(4), vmin: 0, vmax: 100 } as never,
    });
  });

  const field = (title: RegExp) => screen.getByTitle(title) as HTMLInputElement;

  it("refuses min > max instead of storing a window the slider disagrees with", () => {
    render(<AdjustPanel />);
    const before = useViewer.getState().display["a"];
    fireEvent.focus(field(/Minimum/));
    fireEvent.change(field(/Minimum/), { target: { value: "150" } });
    const min = screen.getByDisplayValue("150");
    expect(min).toHaveAttribute("aria-invalid", "true");
    expect(min.title).toMatch(/below the maximum/);
    expect(useViewer.getState().display["a"]?.lo).toBe(before?.lo);
  });

  it.each([
    [/tick interval/, "-1", "tickStep"],
    [/Number of colorbar ticks/, "100000", "tickCount"],
    [/tick-label font/, "-10", "tickFontSize"],
    [/tick-label font/, "1000", "tickFontSize"],
  ] as const)("refuses %s = %s", (title, value, key) => {
    render(<AdjustPanel />);
    fireEvent.focus(field(title));
    fireEvent.change(field(title), { target: { value } });
    expect(screen.getByDisplayValue(value)).toHaveAttribute("aria-invalid", "true");
    expect(useViewer.getState().display["a"]?.[key]).toBeFalsy();
  });
});
