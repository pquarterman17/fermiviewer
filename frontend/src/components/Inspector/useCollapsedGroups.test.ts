// useCollapsedGroups: collapse/expand toggling + localStorage persistence.

import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { useCollapsedGroups } from "./useCollapsedGroups";

describe("useCollapsedGroups", () => {
  beforeEach(() => localStorage.clear());

  it("groups start expanded; toggle collapses and persists", () => {
    const { result } = renderHook(() => useCollapsedGroups("measure"));
    expect(result.current.collapsed.has("ROI")).toBe(false);

    act(() => result.current.toggle("ROI"));
    expect(result.current.collapsed.has("ROI")).toBe(true);
    expect(
      JSON.parse(localStorage.getItem("fv_groups_measure") ?? "[]"),
    ).toEqual(["ROI"]);

    act(() => result.current.toggle("ROI"));
    expect(result.current.collapsed.has("ROI")).toBe(false);
    expect(
      JSON.parse(localStorage.getItem("fv_groups_measure") ?? "[]"),
    ).toEqual([]);
  });

  it("loads persisted collapsed groups on mount", () => {
    localStorage.setItem("fv_groups_x", JSON.stringify(["A", "B"]));
    const { result } = renderHook(() => useCollapsedGroups("x"));
    expect(result.current.collapsed.has("A")).toBe(true);
    expect(result.current.collapsed.has("B")).toBe(true);
    expect(result.current.collapsed.has("C")).toBe(false);
  });

  it("ignores corrupt persisted state", () => {
    localStorage.setItem("fv_groups_x", "{not an array}");
    const { result } = renderHook(() => useCollapsedGroups("x"));
    expect(result.current.collapsed.size).toBe(0);
  });
});
