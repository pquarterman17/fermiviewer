// saveComposite — the on-screen overlay canvas becomes a library image
// (SPECTRAL plan #10, ADR 0003 §2).

import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({
  registerComposite: vi.fn(),
}));

import { registerComposite, type ImageMeta } from "../api";
import { compositeName, saveCompositeToLibrary } from "./saveComposite";

/** A 1×2 canvas stand-in: red pixel then semi-transparent green pixel.
 *  jsdom has no real 2D context, so the shape is faked at the API level. */
function fakeCanvas(): HTMLCanvasElement {
  const rgba = new Uint8ClampedArray([255, 0, 0, 255, 0, 200, 0, 128]);
  return {
    width: 2,
    height: 1,
    getContext: () => ({ getImageData: () => ({ data: rgba }) }),
  } as unknown as HTMLCanvasElement;
}

beforeEach(() => {
  vi.mocked(registerComposite)
    .mockReset()
    .mockResolvedValue({ id: "new", kind: "rgb_image" } as ImageMeta);
});

describe("saveCompositeToLibrary", () => {
  it("strips alpha and posts RGB with the parent and recipe", async () => {
    const meta = await saveCompositeToLibrary({
      canvas: fakeCanvas(),
      parentId: "cube1",
      name: "Composite — Fe",
      recipe: { modality: "eds" },
    });
    expect(meta?.id).toBe("new");
    expect(registerComposite).toHaveBeenCalledWith({
      parentId: "cube1",
      name: "Composite — Fe",
      width: 2,
      height: 1,
      // alpha dropped, colour bytes untouched — what the user saw is what
      // is stored (the blend already premultiplied onto the canvas)
      pixels: new Uint8Array([255, 0, 0, 0, 200, 0]),
      recipe: { modality: "eds" },
    });
  });

  it("returns null (and does not POST) when there is no canvas yet", async () => {
    expect(await saveCompositeToLibrary({ canvas: null, parentId: "p", name: "n" }))
      .toBeNull();
    const empty = { width: 0, height: 0 } as HTMLCanvasElement;
    expect(await saveCompositeToLibrary({ canvas: empty, parentId: "p", name: "n" }))
      .toBeNull();
    expect(registerComposite).not.toHaveBeenCalled();
  });
});

describe("compositeName", () => {
  it("lists the symbols and the parent", () => {
    expect(compositeName(["Fe", "Cu"], "cube.bcf")).toBe(
      "Composite — Fe, Cu (cube.bcf)",
    );
    expect(compositeName([], undefined)).toBe("Composite — empty");
  });
});
