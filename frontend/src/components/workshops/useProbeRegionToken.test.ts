import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Rect1 } from "./RegionPicker";
import { useProbeRegionToken } from "./useProbeRegionToken";

const PIXEL: Rect1 = [10, 14, 10, 14];
const BIG: Rect1 = [1, 1, 50, 50];

describe("useProbeRegionToken", () => {
  it("skips the load for the region the probe just published", () => {
    const { result } = renderHook(() => useProbeRegionToken());
    result.current.mark(PIXEL);
    expect(result.current.consumeIfMatches([...PIXEL] as Rect1)).toBe(true);
  });

  it("skips ONCE — a later return to the same region still reloads", () => {
    // The regression. The marker used to be written and never cleared, so the
    // guard kept matching forever: re-picking that exact rect later skipped
    // both the refetch AND the spectrum/fit/quant reset, leaving stale data
    // on screen under a correct-looking region label.
    const { result } = renderHook(() => useProbeRegionToken());
    result.current.mark(PIXEL);

    expect(result.current.consumeIfMatches([...PIXEL] as Rect1)).toBe(true);
    // user drags a big region, then comes back to the same pixel by hand
    expect(result.current.consumeIfMatches(BIG)).toBe(false);
    expect(result.current.consumeIfMatches([...PIXEL] as Rect1)).toBe(false);
  });

  it("does not skip a region the probe never published", () => {
    const { result } = renderHook(() => useProbeRegionToken());
    result.current.mark(PIXEL);
    expect(result.current.consumeIfMatches(BIG)).toBe(false);
    // the unrelated region must not have consumed the pending marker
    expect(result.current.consumeIfMatches([...PIXEL] as Rect1)).toBe(true);
  });

  it("never skips a null region (whole-image load)", () => {
    const { result } = renderHook(() => useProbeRegionToken());
    result.current.mark(PIXEL);
    expect(result.current.consumeIfMatches(null)).toBe(false);
  });

  it("clear() drops a pending marker, so the next load runs", () => {
    // Switching images: a marker from the previous image must not suppress
    // the new image's first load.
    const { result } = renderHook(() => useProbeRegionToken());
    result.current.mark(PIXEL);
    result.current.clear();
    expect(result.current.consumeIfMatches([...PIXEL] as Rect1)).toBe(false);
  });

  it("re-marking the same region re-arms the one-shot skip", () => {
    // Probing the same pixel twice: each publish carries its own spectrum, so
    // each one earns a skip.
    const { result } = renderHook(() => useProbeRegionToken());
    result.current.mark(PIXEL);
    expect(result.current.consumeIfMatches([...PIXEL] as Rect1)).toBe(true);
    result.current.mark(PIXEL);
    expect(result.current.consumeIfMatches([...PIXEL] as Rect1)).toBe(true);
  });

  it("keeps a stable identity across re-renders", () => {
    // The workshop reads this from inside an effect that does not list it as a
    // dependency; a new object each render would silently capture a stale one.
    const { result, rerender } = renderHook(() => useProbeRegionToken());
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });
});
