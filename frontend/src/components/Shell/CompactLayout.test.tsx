import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const toggleLeft = vi.fn();
const state = { leftCol: false, toggleLeft };

vi.mock("../../store/viewer", () => ({
  useViewer: { getState: () => state },
}));

import CompactLayout from "./CompactLayout";

describe("CompactLayout", () => {
  beforeEach(() => {
    toggleLeft.mockClear();
    state.leftCol = false;
  });

  it("collapses the library when the window enters compact width", () => {
    let change: ((event: { matches: boolean }) => void) | undefined;
    vi.spyOn(window, "matchMedia").mockReturnValue({
      matches: false,
      addEventListener: (_name: string, listener: EventListenerOrEventListenerObject) => {
        change = listener as unknown as (event: { matches: boolean }) => void;
      },
      removeEventListener: vi.fn(),
    } as unknown as MediaQueryList);

    render(<CompactLayout />);
    expect(toggleLeft).not.toHaveBeenCalled();
    change?.({ matches: true });
    expect(toggleLeft).toHaveBeenCalledOnce();
  });

  it("preserves an already-collapsed library", () => {
    state.leftCol = true;
    vi.spyOn(window, "matchMedia").mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    } as unknown as MediaQueryList);

    render(<CompactLayout />);
    expect(toggleLeft).not.toHaveBeenCalled();
  });
});
