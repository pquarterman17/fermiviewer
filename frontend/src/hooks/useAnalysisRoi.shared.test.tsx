import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { useWorkshop } from "../store/workshop";
import { useViewer } from "../store/viewer";
import { useAnalysisRoi } from "./useAnalysisRoi";

afterEach(() => {
  useWorkshop.setState({ analysisRegionChoices: {} });
  useViewer.setState({ savedRois: {} });
});

describe("shared analysis region", () => {
  it("persists the choice by source image across hook consumers", () => {
    useViewer.setState({ savedRois: { src: [{
      id: "film", name: "Film", kind: "roi",
      pts: [{ x: 0.1, y: 0.2 }, { x: 0.9, y: 0.8 }],
      createdAt: "2026-07-19T00:00:00Z",
    }] } });
    const first = renderHook(() => useAnalysisRoi("src", [100, 100]));
    act(() => first.result.current.setChoice("saved:film"));
    const second = renderHook(() => useAnalysisRoi("src", [100, 100]));
    expect(second.result.current.choice).toBe("saved:film");
    expect(second.result.current.roi).toEqual([21, 11, 80, 90]);
    expect(useWorkshop.getState().analysisRegionChoices.src).toBe("saved:film");
  });
});
