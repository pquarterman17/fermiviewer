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

  it("adds an explanatory line only when data-tip-detail is provided", () => {
    render(
      <>
        <button
          data-tip="ROI statistics"
          data-tip-detail="Drag a region to calculate summary statistics."
        >
          ROI
        </button>
        <TooltipLayer />
      </>,
    );
    act(() => {
      screen
        .getByText("ROI")
        .dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
    });
    act(() => vi.advanceTimersByTime(400));
    expect(screen.getByRole("tooltip")).toHaveTextContent("ROI statistics");
    expect(screen.getByRole("tooltip")).toHaveTextContent(
      "Drag a region to calculate summary statistics.",
    );
  });

  it("does not re-show its own tooltip when a click focuses the button", () => {
    // mousedown dismisses, then the browser focuses the clicked button. Without
    // an input-modality guard, focusin re-armed the dwell timer and the tooltip
    // reappeared 350 ms after every click.
    render(
      <>
        <button data-tip="Measure distance">⤢</button>
        <TooltipLayer />
      </>,
    );
    const btn = screen.getByText("⤢");

    act(() => {
      btn.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
    });
    act(() => vi.advanceTimersByTime(400));
    expect(screen.getByText("Measure distance")).toBeInTheDocument();

    act(() => {
      btn.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
      btn.dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
    });
    act(() => vi.advanceTimersByTime(400));
    expect(screen.queryByText("Measure distance")).toBeNull();
  });

  it("still shows on keyboard focus, so descriptions stay reachable", () => {
    // The click guard must not cost WCAG 1.4.13 hover/focus parity.
    render(
      <>
        <button data-tip="Measure distance">⤢</button>
        <TooltipLayer />
      </>,
    );
    const btn = screen.getByText("⤢");

    act(() => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true }));
      btn.dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
    });
    act(() => vi.advanceTimersByTime(400));
    expect(screen.getByText("Measure distance")).toBeInTheDocument();
  });

  it("does not strand a tooltip for a trigger removed during the dwell", () => {
    // Buttons that unmount on click (delete-last-annotation) emit neither
    // mouseout nor focusout, so a chip shown for one could never be dismissed.
    // TooltipLayer must stay FIRST and mounted across the rerender: if it
    // shifts position React unmounts it, and its cleanup clears the pending
    // timer — the test would then pass without the guard under test.
    const { rerender } = render(
      <>
        <TooltipLayer />
        <button data-tip="Delete last annotation">✕</button>
      </>,
    );
    act(() => {
      screen
        .getByText("✕")
        .dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
    });

    rerender(
      <>
        <TooltipLayer />
      </>,
    );
    act(() => vi.advanceTimersByTime(400));
    expect(screen.queryByText("Delete last annotation")).toBeNull();
  });
});
