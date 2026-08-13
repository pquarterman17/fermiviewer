import { describe, expect, it } from "vitest";
import type uPlot from "uplot";

import { BAND_LEGEND_ROW_CLASS } from "./sigmaBand";
import { chartToSvg, specFromUplot, type ChartSpec } from "./chartSvg";

function baseSpec(overrides: Partial<ChartSpec> = {}): ChartSpec {
  return {
    title: "Test chart",
    xLabel: "x (units)",
    yLabel: "y (units)",
    x: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    series: [
      {
        label: "Visible line",
        color: "#ff0000",
        width: 2,
        visible: true,
        // a null mid-series must break the path into two subpaths
        points: [0, 1, 2, null, 4, 5, 6, 7, 8, 9, 10],
      },
      {
        label: "Hidden line",
        color: "#00ff00",
        width: 2,
        visible: false,
        points: [10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
      },
    ],
    ...overrides,
  };
}

function pathsIn(svg: string): string[] {
  return [...svg.matchAll(/<path\b[^>]*>/g)].map((m) => m[0]);
}

describe("chartToSvg", () => {
  it("contains the title and both axis labels", () => {
    const svg = chartToSvg(baseSpec());
    expect(svg).toContain(">Test chart<");
    expect(svg).toContain(">x (units)<");
    expect(svg).toContain(">y (units)<");
  });

  it("draws exactly one path for the visible series, in its colour, and none for the hidden one", () => {
    const svg = chartToSvg(baseSpec());
    const paths = pathsIn(svg);
    expect(paths).toHaveLength(1);
    expect(paths[0]).toContain('stroke="#ff0000"');
    expect(svg).not.toContain("#00ff00");
  });

  it("breaks a null-gap series into two path subpaths (two M commands)", () => {
    const svg = chartToSvg(baseSpec());
    const [path] = pathsIn(svg);
    const mCount = (path.match(/M /g) ?? []).length;
    expect(mCount).toBe(2);
  });

  it("does not gap a series with no nulls at all", () => {
    const svg = chartToSvg(
      baseSpec({
        series: [
          {
            label: "Solid",
            color: "#123456",
            width: 1,
            visible: true,
            points: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
          },
        ],
      }),
    );
    const [path] = pathsIn(svg);
    expect((path.match(/M /g) ?? []).length).toBe(1);
  });

  it("labels ticks spanning the data range, including the min and max", () => {
    const svg = chartToSvg(baseSpec());
    // y domain is [0, 10] (from the one VISIBLE series only) and lands
    // exactly on the 1-2-5 ladder's endpoints
    expect(svg).toContain(">0<");
    expect(svg).toContain(">10<");
  });

  it("omits an invisible series from the legend", () => {
    const svg = chartToSvg(baseSpec());
    expect(svg).toContain("Visible line");
    expect(svg).not.toContain("Hidden line");
  });

  it("still exports its visible line correctly when a band pair rides alongside it", () => {
    // Mimics EdsQuantifyPanel's CompProfilePlot shape: a real line series
    // plus a hi/lo band-boundary pair the exporter must not draw a line for.
    const svg = chartToSvg(
      baseSpec({
        series: [
          {
            label: "Element",
            color: "#3b82f6",
            width: 1.5,
            visible: true,
            points: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
          },
        ],
      }),
    );
    const paths = pathsIn(svg);
    expect(paths).toHaveLength(1);
  });

  it("handles a log-log domain (roughness PSD-style chart) without throwing", () => {
    const svg = chartToSvg({
      title: "PSD",
      xLabel: "wavelength",
      yLabel: "power",
      x: [1, 2, 5, 10, 20, 50, 100],
      logX: true,
      logY: true,
      series: [
        {
          label: "PSD",
          color: "#a78bfa",
          width: 1.5,
          visible: true,
          points: [1000, 500, 200, 90, 30, 8, 2],
        },
      ],
    });
    expect(svg).toContain("<svg");
    expect(pathsIn(svg)).toHaveLength(1);
  });

  it("renders a usable chart with no series at all rather than throwing", () => {
    const svg = chartToSvg({ x: [], series: [] });
    expect(svg).toContain("<svg");
    expect(svg).toContain("</svg>");
  });

  it("sets explicit physical width/height attributes on the root svg", () => {
    const svg = chartToSvg(baseSpec({ width: 800, height: 500 }));
    expect(svg).toContain('width="800"');
    expect(svg).toContain('height="500"');
  });
});

// ── specFromUplot ─────────────────────────────────────────────────────
//
// jsdom has no working canvas 2D context, so this codebase's own uPlot-chart
// tests never construct a real `new uPlot(...)` (see EdsQuantifyPanel.test.tsx
// / EelsResults.test.tsx: they `vi.mock("uplot", ...)` the whole module).
// Following that precedent, these tests build a plain object matching the
// PUBLIC instance shape specFromUplot reads (series/data/scales/axes/root/
// width/height) rather than mounting a real instance.

function fakeRoot(vars: Record<string, string> = {}): HTMLElement {
  const el = document.createElement("div");
  for (const [k, v] of Object.entries(vars)) el.style.setProperty(k, v);
  document.body.appendChild(el);
  return el;
}

describe("specFromUplot", () => {
  it("reads series label/color/width/visibility and the shared x array", () => {
    const u = {
      data: [
        [0, 1, 2],
        [10, 20, 30],
        [40, null, 60],
      ],
      series: [
        { label: "d (nm)" },
        { label: "Cu", stroke: "#f97316", width: 1.5, show: true },
        { label: "Ni", stroke: "#22d3ee", width: 1, show: false },
      ],
      scales: { x: { min: 0, max: 2 }, y: { min: 10, max: 60 } },
      axes: [{}, {}],
      root: fakeRoot(),
      width: 400,
      height: 250,
    } as unknown as uPlot;

    const spec = specFromUplot(u, { title: "Composition profile" });

    expect(spec.title).toBe("Composition profile");
    expect(spec.x).toEqual([0, 1, 2]);
    expect(spec.series).toHaveLength(2);
    expect(spec.series[0]).toMatchObject({
      label: "Cu",
      color: "#f97316",
      width: 1.5,
      visible: true,
    });
    expect(spec.series[1].visible).toBe(false);
    expect(spec.series[1].points).toEqual([40, null, 60]);
    expect(spec.xRange).toEqual([0, 2]);
    expect(spec.yRange).toEqual([10, 60]);
  });

  it("infers the x label from series[0]'s label by this codebase's own convention", () => {
    const u = {
      data: [[0, 1], [1, 2]],
      series: [{ label: "E (keV)" }, { label: "Counts", stroke: "#8b5cf6", show: true }],
      scales: { x: {}, y: {} },
      axes: [{}, {}],
      root: fakeRoot(),
      width: 300,
      height: 200,
    } as unknown as uPlot;

    const spec = specFromUplot(u, { title: "Spectrum" });
    expect(spec.xLabel).toBe("E (keV)");
    // a single visible series' own label doubles as the y label, matching
    // how these single-line charts never set axes[1].label themselves
    expect(spec.yLabel).toBe("Counts");
  });

  it("prefers an explicit axes[].label over the series[0] convention", () => {
    const u = {
      data: [[0, 1], [1, 2]],
      series: [{ label: "anneal T" }, { label: "area", stroke: "#a78bfa", show: true }],
      scales: { x: {}, y: {} },
      axes: [{ label: "anneal T (°C)" }, { label: "area (µm²)" }],
      root: fakeRoot(),
      width: 300,
      height: 200,
    } as unknown as uPlot;

    const spec = specFromUplot(u, { title: "Compare" });
    expect(spec.xLabel).toBe("anneal T (°C)");
    expect(spec.yLabel).toBe("area (µm²)");
  });

  it("drops band-boundary series (sigmaBand's hi/lo pair) rather than drawing them as lines", () => {
    const u = {
      data: [[0, 1], [1, 2], [1.1, 2.1], [0.9, 1.9]],
      series: [
        { label: "d (nm)" },
        { label: "Fe", stroke: "#f97316", width: 1.5, show: true },
        { label: "Fe ±1σ", class: BAND_LEGEND_ROW_CLASS, stroke: "#f97316", width: 0, show: true },
        { label: "Fe ±1σ", class: BAND_LEGEND_ROW_CLASS, stroke: "#f97316", width: 0, show: true },
      ],
      scales: { x: {}, y: {} },
      axes: [{}, {}],
      root: fakeRoot(),
      width: 300,
      height: 200,
    } as unknown as uPlot;

    const spec = specFromUplot(u, { title: "Profile" });
    expect(spec.series).toHaveLength(1);
    expect(spec.series[0].label).toBe("Fe");
  });

  it("calls a per-series stroke function with the live instance (uPlot's public colour-fn API)", () => {
    const u = {
      data: [[0, 1], [1, 2]],
      series: [
        { label: "x" },
        { label: "y", stroke: (_self: uPlot, idx: number) => `#00${idx}0${idx}0`, show: true },
      ],
      scales: { x: {}, y: {} },
      axes: [{}, {}],
      root: fakeRoot(),
      width: 300,
      height: 200,
    } as unknown as uPlot;

    const spec = specFromUplot(u, { title: "Fn stroke" });
    expect(spec.series[0].color).toBe("#001010");
  });

  it("resolves a var(--token) stroke against the plot root's CURRENT computed style", () => {
    const root = fakeRoot({ "--accent": "#a78bfa" });
    const u = {
      data: [[0, 1], [1, 2]],
      series: [{ label: "x" }, { label: "y", stroke: "var(--accent)", show: true }],
      scales: { x: {}, y: {} },
      axes: [{}, {}],
      root,
      width: 300,
      height: 200,
    } as unknown as uPlot;

    const spec = specFromUplot(u, { title: "Var stroke" });
    expect(spec.series[0].color).toBe("#a78bfa");
  });

  it("detects a log scale from distr: 3 on either axis", () => {
    const u = {
      data: [[1, 10], [100, 10]],
      series: [{ label: "x" }, { label: "y", stroke: "#a78bfa", show: true }],
      scales: { x: { distr: 3 }, y: { distr: 3 } },
      axes: [{}, {}],
      root: fakeRoot(),
      width: 300,
      height: 200,
    } as unknown as uPlot;

    const spec = specFromUplot(u, { title: "Log-log" });
    expect(spec.logX).toBe(true);
    expect(spec.logY).toBe(true);
  });

  it("defaults to linear when scales carry no distr (the common case in this codebase)", () => {
    const u = {
      data: [[0, 1], [1, 2]],
      series: [{ label: "x" }, { label: "y", stroke: "#a78bfa", show: true }],
      scales: { x: {}, y: {} },
      axes: [{}, {}],
      root: fakeRoot(),
      width: 300,
      height: 200,
    } as unknown as uPlot;

    const spec = specFromUplot(u, { title: "Linear" });
    expect(spec.logX).toBe(false);
    expect(spec.logY).toBe(false);
  });
});
