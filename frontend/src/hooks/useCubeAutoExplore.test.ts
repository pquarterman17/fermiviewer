import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import type { ImageMeta } from "../lib/api";
import { useViewer } from "../store/viewer";
import { useCubeAutoExplore } from "./useCubeAutoExplore";

function meta(id: string, extra: Partial<ImageMeta> = {}): ImageMeta {
  return {
    id,
    name: `${id}.bcf`,
    kind: "image",
    shape: [96, 128],
    dtype: "float64",
    pixel_size: 0.5,
    pixel_unit: "nm",
    n_channels: null,
    energy_first: null,
    energy_last: null,
    energy_units: "",
    stage_tilt_deg: null,
    meta: {},
    ...extra,
  } as ImageMeta;
}

const edsOpen = () =>
  useViewer.getState().tools.some((t) => t.kind === "eds");

describe("useCubeAutoExplore", () => {
  beforeEach(() => useViewer.setState(useViewer.getInitialState()));

  it("opens the EDS explorer when a spectrum-image cube becomes active", () => {
    useViewer.getState().ingest([meta("cube", { kind: "spectrum_image" })]);
    renderHook(() => useCubeAutoExplore());
    act(() => useViewer.getState().setActive("cube"));
    expect(edsOpen()).toBe(true);
  });

  it("does not open the explorer for a plain image", () => {
    useViewer.getState().ingest([meta("img", { kind: "image" })]);
    renderHook(() => useCubeAutoExplore());
    act(() => useViewer.getState().setActive("img"));
    expect(edsOpen()).toBe(false);
  });

  it("does not force the explorer back open after the user closed it", () => {
    useViewer
      .getState()
      .ingest([meta("cube", { kind: "spectrum_image" }), meta("img")]);
    renderHook(() => useCubeAutoExplore());
    act(() => useViewer.getState().setActive("cube"));
    expect(edsOpen()).toBe(true); // auto-opened once

    act(() => useViewer.getState().closeTool("eds"));
    act(() => useViewer.getState().setActive("img"));
    act(() => useViewer.getState().setActive("cube")); // revisit the same cube
    expect(edsOpen()).toBe(false); // stays closed — fires once per image
  });
});
