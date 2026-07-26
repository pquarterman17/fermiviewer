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
const eelsOpen = () =>
  useViewer.getState().tools.some((t) => t.kind === "eels");

describe("useCubeAutoExplore", () => {
  beforeEach(() => useViewer.setState(useViewer.getInitialState()));

  it("opens the EDS explorer when a spectrum-image cube becomes active", () => {
    useViewer
      .getState()
      .ingest([
        meta("cube", { kind: "spectrum_image", meta: { parser: "bcf" } }),
      ]);
    renderHook(() => useCubeAutoExplore());
    act(() => useViewer.getState().setActive("cube"));
    expect(edsOpen()).toBe(true);
  });

  it("routes a core-loss cube to EELS instead of EDS", () => {
    useViewer.getState().ingest([
      meta("core-loss", {
        kind: "spectrum_image",
        energy_first: 490,
        energy_last: 590,
        energy_units: "eV",
      }),
    ]);
    renderHook(() => useCubeAutoExplore());
    act(() => useViewer.getState().setActive("core-loss"));
    expect(eelsOpen()).toBe(true);
    expect(edsOpen()).toBe(false);
  });

  it("asks for ambiguous cubes and remembers the selected workflow", () => {
    useViewer.getState().ingest([
      meta("ambiguous", {
        kind: "spectrum_image",
        energy_first: 0,
        energy_last: 2000,
        energy_units: "eV",
      }),
    ]);
    const { result } = renderHook(() => useCubeAutoExplore());
    act(() => useViewer.getState().setActive("ambiguous"));
    expect(result.current.pending?.id).toBe("ambiguous");
    act(() => result.current.choose("eds"));
    expect(edsOpen()).toBe(true);
    expect(result.current.pending).toBeNull();
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
      .ingest([
        meta("cube", { kind: "spectrum_image", meta: { parser: "bcf" } }),
        meta("img"),
      ]);
    renderHook(() => useCubeAutoExplore());
    act(() => useViewer.getState().setActive("cube"));
    expect(edsOpen()).toBe(true); // auto-opened once

    act(() => useViewer.getState().closeTool("eds"));
    act(() => useViewer.getState().setActive("img"));
    act(() => useViewer.getState().setActive("cube")); // revisit the same cube
    expect(edsOpen()).toBe(false); // stays closed — fires once per image
  });
});
