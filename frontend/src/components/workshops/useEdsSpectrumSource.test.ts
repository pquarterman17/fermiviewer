// EDS spectrum requests: only the newest request may set the spectrum or
// clear `busy`, whatever order the responses arrive in.
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Spectrum } from "../../lib/api";

type Deferred = { resolve: (s: Spectrum) => void; signal?: AbortSignal };
const calls: Deferred[] = [];
vi.mock("../../lib/api", async (importActual) => ({
  ...(await importActual<typeof import("../../lib/api")>()),
  fetchSpectrum: vi.fn(
    (_id: string, _rect?: unknown, options?: { signal?: AbortSignal }) =>
      new Promise<Spectrum>((resolve) => {
        calls.push({ resolve, signal: options?.signal });
      }),
  ),
}));
let probeSample: ((s: Spectrum, rect: number[]) => void) | null = null;
vi.mock("./useSpectrumProbe", () => ({
  useSpectrumProbe: (o: { onSpectrum: (s: Spectrum, rect: number[]) => void }) => {
    probeSample = o.onSpectrum;
  },
}));

import { useEdsSpectrumSource } from "./useEdsSpectrumSource";

const spec = (tag: number): Spectrum => ({ energy: [tag], counts: [tag], units: "keV" });

function setup(initial = "a", open = () => true) {
  const onStatus = vi.fn();
  const hook = renderHook(
    ({ id }) =>
      useEdsSpectrumSource({
        imageId: id,
        enabled: true,
        probePixel: null,
        probeActive: false,
        isOpen: ((x: string | null) => x !== null && open()) as (x: string | null) => x is string,
        onStatus,
        onLoaded: () => {},
      }),
    { initialProps: { id: initial } },
  );
  return { ...hook, onStatus };
}

afterEach(() => {
  calls.length = 0;
  probeSample = null;
});

describe("useEdsSpectrumSource", () => {
  it("keeps the newest ROI when an older one lands later", async () => {
    const { result } = setup();
    await act(async () => calls[0].resolve(spec(0))); // the sum
    act(() => result.current.showRegion([1, 1, 2, 2]));
    act(() => result.current.showRegion([3, 3, 4, 4]));
    expect(calls[1].signal?.aborted).toBe(true);
    await act(async () => calls[2].resolve(spec(2)));
    expect(result.current.busy).toBe(false);
    await act(async () => calls[1].resolve(spec(1))); // stale, arrives late
    expect(result.current.spectrum?.counts).toEqual([2]);
    expect(result.current.label).toBe("ROI [3:4, 3:4]");
  });

  it("busy belongs to the newest request", async () => {
    const { result } = setup();
    await act(async () => calls[0].resolve(spec(0)));
    act(() => result.current.showRegion([1, 1, 2, 2]));
    act(() => result.current.showRegion([3, 3, 4, 4]));
    await act(async () => calls[1].resolve(spec(1))); // the older one finishes first
    expect(result.current.busy).toBe(true);
    await act(async () => calls[2].resolve(spec(2)));
    expect(result.current.busy).toBe(false);
  });

  it("drops a response for the cube it switched away from", async () => {
    const { result, rerender } = setup("a");
    act(() => result.current.showRegion([1, 1, 2, 2])); // a's ROI in flight
    rerender({ id: "b" }); // a is still open in the library
    expect(calls[1].signal?.aborted).toBe(true);
    await act(async () => calls[1].resolve(spec(1)));
    await act(async () => calls[2].resolve(spec(9))); // b's sum
    expect(result.current.spectrum?.counts).toEqual([9]);
  });

  it("a live-probe sample or the cached sum supersedes a pending ROI", async () => {
    const { result } = setup();
    await act(async () => calls[0].resolve(spec(0)));
    act(() => result.current.showRegion([1, 1, 2, 2]));
    act(() => probeSample?.(spec(5), [3, 3, 3, 3]));
    expect(result.current.busy).toBe(false);
    await act(async () => calls[1].resolve(spec(1)));
    expect(result.current.spectrum?.counts).toEqual([5]);
    act(() => result.current.showRegion([1, 1, 2, 2]));
    act(() => result.current.showSum());
    await act(async () => calls[2].resolve(spec(2)));
    expect(result.current.source).toBe("sum");
    expect(result.current.spectrum?.counts).toEqual([0]);
  });

  it("does not report an aborted request as an error", async () => {
    const { result, onStatus } = setup();
    act(() => result.current.showRegion([1, 1, 2, 2]));
    expect(calls[0].signal?.aborted).toBe(true);
    expect(onStatus).not.toHaveBeenCalled();
  });
});
