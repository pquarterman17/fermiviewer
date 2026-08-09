// stageOps databar actions — Thermo Fisher SEM/FIB TIFFs bake an info strip
// into the bottom of the pixels; this is the "strip it" path plus the
// predicate that drives the Image ▸ Transform item's enabled state.

import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ImageMeta } from "./api";

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  stripDatabar: vi.fn(),
}));

import { useViewer } from "../store/viewer";
import { stripDatabar as stripDatabarApi } from "./api";
import { databarRows, hasDatabar, stripDatabar } from "./stageOps";

// A Helios frame: 1103 rows on disk, 1024 scanned, 79 of databar.
const FEI = {
  id: "a",
  name: "fib.tif",
  kind: "image",
  shape: [1103, 1536],
  dtype: "uint16",
  content_rows: 1024,
  meta: {},
} as ImageMeta;

const PLAIN = { ...FEI, id: "b", name: "plain.dm4", content_rows: null };

beforeEach(() => {
  vi.mocked(stripDatabarApi).mockReset();
  vi.mocked(stripDatabarApi).mockResolvedValue({
    ...FEI,
    id: "c",
    name: "nobar(fib.tif)",
    shape: [1024, 1536],
    content_rows: null,
  } as ImageMeta);
  useViewer.setState({ activeId: "a", images: { a: FEI, b: PLAIN } });
});

describe("databarRows", () => {
  it("reports the content rows for an image with a baked bar", () => {
    expect(databarRows(FEI)).toBe(1024);
  });

  it("is null when there is nothing to strip", () => {
    expect(databarRows(PLAIN)).toBeNull();
    expect(databarRows(undefined)).toBeNull();
    // content_rows equal to the array height means "no bar", not "crop 0"
    expect(databarRows({ ...FEI, content_rows: 1103 } as ImageMeta)).toBeNull();
  });

  it("rejects a row count the array cannot support", () => {
    // Re-checked client-side so a stale meta (e.g. content_rows surviving a
    // resample that shrank the image) can never drive a crop that would
    // grow the image or empty it.
    expect(databarRows({ ...FEI, content_rows: 4096 } as ImageMeta)).toBeNull();
    expect(databarRows({ ...FEI, content_rows: 0 } as ImageMeta)).toBeNull();
    expect(databarRows({ ...FEI, content_rows: -79 } as ImageMeta)).toBeNull();
  });
});

describe("hasDatabar", () => {
  it("tracks the active image", () => {
    expect(hasDatabar()).toBe(true);
    useViewer.setState({ activeId: "b" });
    expect(hasDatabar()).toBe(false);
    useViewer.setState({ activeId: null });
    expect(hasDatabar()).toBe(false);
  });
});

describe("stripDatabar", () => {
  it("calls the endpoint with no rect — the server owns the geometry", async () => {
    expect(stripDatabar()).toBe(true);
    expect(stripDatabarApi).toHaveBeenCalledExactlyOnceWith("a");
    await vi.waitFor(() =>
      expect(useViewer.getState().images.c?.shape).toEqual([1024, 1536]),
    );
    expect(useViewer.getState().status).toContain("databar stripped");
  });

  it("refuses an image with no databar instead of cropping blind", () => {
    useViewer.setState({ activeId: "b" });
    expect(stripDatabar()).toBe(false);
    expect(stripDatabarApi).not.toHaveBeenCalled();
    expect(useViewer.getState().status).toContain("no vendor databar");
  });

  it("surfaces a server refusal in the status bar", async () => {
    vi.mocked(stripDatabarApi).mockRejectedValue(
      new Error("no vendor databar recorded for this image"),
    );
    stripDatabar();
    await vi.waitFor(() =>
      expect(useViewer.getState().status).toContain("strip databar:"),
    );
  });
});
