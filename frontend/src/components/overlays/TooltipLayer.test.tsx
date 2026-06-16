// TooltipLayer: delegated [data-tip] hover tooltip. Fake timers drive the
// dwell delay; the tip is portalled to document.body so screen queries find it.

import { render, screen } from "@testing-library/react";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import TooltipLayer from "./TooltipLayer";

describe("TooltipLayer", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("shows the label + shortcut after the dwell and hides on mouseout", () => {
    render(
      <>
        <button data-tip="Measure distance" data-tip-key="D">
          ⤢
        </button>
        <TooltipLayer />
      </>,
    );
    const btn = screen.getByText("⤢");

    act(() => {
      btn.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
    });
    // nothing shows before the dwell elapses
    expect(screen.queryByText("Measure distance")).toBeNull();

    act(() => vi.advanceTimersByTime(400));
    expect(screen.getByText("Measure distance")).toBeInTheDocument();
    expect(screen.getByText("D")).toBeInTheDocument(); // shortcut in <kbd>

    act(() => {
      document.dispatchEvent(new MouseEvent("mouseout", { bubbles: true }));
    });
    expect(screen.queryByText("Measure distance")).toBeNull();
  });

  it("renders a tip with no shortcut when data-tip-key is absent", () => {
    render(
      <>
        <button data-tip="Thumbnail view">▦</button>
        <TooltipLayer />
      </>,
    );
    act(() => {
      screen
        .getByText("▦")
        .dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
    });
    act(() => vi.advanceTimersByTime(400));
    expect(screen.getByText("Thumbnail view")).toBeInTheDocument();
  });
});
