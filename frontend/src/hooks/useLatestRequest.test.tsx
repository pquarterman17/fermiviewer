import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useLatestRequest } from "./useLatestRequest";

describe("useLatestRequest", () => {
  it("invalidates and aborts the previous request when a newer one starts", () => {
    const { result } = renderHook(() => useLatestRequest("a"));
    const first = result.current.begin();
    const second = result.current.begin();

    expect(first.signal.aborted).toBe(true);
    expect(first.isCurrent()).toBe(false);
    expect(second.signal.aborted).toBe(false);
    expect(second.isCurrent()).toBe(true);
  });

  it("invalidates the request when its source scope changes", () => {
    const { result, rerender } = renderHook(
      ({ source }) => useLatestRequest(source),
      { initialProps: { source: "a" } },
    );
    const request = result.current.begin();

    act(() => rerender({ source: "b" }));

    expect(request.signal.aborted).toBe(true);
    expect(request.isCurrent()).toBe(false);
  });

  it("invalidates the request on unmount", () => {
    const { result, unmount } = renderHook(() => useLatestRequest("a"));
    const request = result.current.begin();

    unmount();

    expect(request.signal.aborted).toBe(true);
    expect(request.isCurrent()).toBe(false);
  });
});
