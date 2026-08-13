import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../lib/api", () => ({ listFourD: vi.fn() }));

import { listFourD } from "../../../lib/api";
import { useFourD } from "../../../store/fourd";
import { useFourDDatasetRefresh } from "./useFourDDatasetRefresh";

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => state,
  });
}

beforeEach(() => {
  vi.mocked(listFourD).mockReset().mockResolvedValue([]);
  setVisibility("visible");
});

afterEach(() => {
  useFourD.getState().reset();
});

describe("useFourDDatasetRefresh", () => {
  it("fetches the dataset list once on mount", async () => {
    renderHook(() => useFourDDatasetRefresh());
    await act(() => Promise.resolve());
    expect(listFourD).toHaveBeenCalledOnce();
  });

  it("refetches when the document becomes visible again", async () => {
    renderHook(() => useFourDDatasetRefresh());
    await act(() => Promise.resolve());
    expect(listFourD).toHaveBeenCalledOnce();

    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await Promise.resolve();
    });
    expect(listFourD).toHaveBeenCalledTimes(2);
  });

  it("does not refetch on a visibilitychange event while the tab is hidden", async () => {
    renderHook(() => useFourDDatasetRefresh());
    await act(() => Promise.resolve());
    expect(listFourD).toHaveBeenCalledOnce();

    setVisibility("hidden");
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await Promise.resolve();
    });
    expect(listFourD).toHaveBeenCalledOnce();
  });

  it("refetches on window focus", async () => {
    renderHook(() => useFourDDatasetRefresh());
    await act(() => Promise.resolve());
    expect(listFourD).toHaveBeenCalledOnce();

    await act(async () => {
      window.dispatchEvent(new Event("focus"));
      await Promise.resolve();
    });
    expect(listFourD).toHaveBeenCalledTimes(2);
  });

  it("removes its listeners on unmount", async () => {
    const { unmount } = renderHook(() => useFourDDatasetRefresh());
    await act(() => Promise.resolve());
    expect(listFourD).toHaveBeenCalledOnce();

    unmount();
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      window.dispatchEvent(new Event("focus"));
      await Promise.resolve();
    });
    expect(listFourD).toHaveBeenCalledOnce();
  });
});
