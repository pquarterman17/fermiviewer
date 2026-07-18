// rename.ts (#43) — single-image rename flow: ParamDialog prompt →
// /image/{id}/rename → store update. API + dialog are mocked.

import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ImageMeta } from "./api";

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  renameImage: vi.fn(),
}));
vi.mock("../store/params", () => ({
  askParams: vi.fn(),
}));

import { askParams } from "../store/params";
import { useViewer } from "../store/viewer";
import { renameImage } from "./api";
import { renameSingleImage } from "./rename";

const initialState = useViewer.getState();

function meta(id: string, name: string): ImageMeta {
  return {
    id,
    name,
    kind: "image",
    shape: [8, 8],
    dtype: "float64",
    pixel_size: null,
    pixel_unit: "",
    n_channels: null,
    energy_first: null,
    energy_last: null,
    energy_units: "",
    stage_tilt_deg: null,
    meta: {},
  } as ImageMeta;
}

beforeEach(() => {
  useViewer.setState(initialState, true);
  vi.clearAllMocks();
  useViewer.getState().ingest([meta("img1", "old.dm4")]);
});

describe("renameSingleImage", () => {
  it("happy path: prompts with the current name, updates the store", async () => {
    vi.mocked(askParams).mockResolvedValue({ name: "new-name" });
    vi.mocked(renameImage).mockResolvedValue(meta("img1", "new-name"));

    await renameSingleImage("img1");

    expect(askParams).toHaveBeenCalledWith("Rename Image", [
      { key: "name", label: "Name", type: "text", default: "old.dm4" },
    ]);
    expect(renameImage).toHaveBeenCalledWith("img1", "new-name");
    expect(useViewer.getState().images["img1"].name).toBe("new-name");
    expect(useViewer.getState().status).toContain("renamed to new-name");
  });

  it("cancel → no API call, store untouched", async () => {
    vi.mocked(askParams).mockResolvedValue(null);
    await renameSingleImage("img1");
    expect(renameImage).not.toHaveBeenCalled();
    expect(useViewer.getState().images["img1"].name).toBe("old.dm4");
  });

  it("unchanged or whitespace-only name → no API call", async () => {
    vi.mocked(askParams).mockResolvedValue({ name: "old.dm4" });
    await renameSingleImage("img1");
    vi.mocked(askParams).mockResolvedValue({ name: "   " });
    await renameSingleImage("img1");
    expect(renameImage).not.toHaveBeenCalled();
  });

  it("unknown image id is a no-op (no prompt)", async () => {
    await renameSingleImage("ghost");
    expect(askParams).not.toHaveBeenCalled();
  });

  it("API failure surfaces in status, name unchanged", async () => {
    vi.mocked(askParams).mockResolvedValue({ name: "boom" });
    vi.mocked(renameImage).mockRejectedValue(new Error("409 duplicate"));
    await renameSingleImage("img1");
    expect(useViewer.getState().images["img1"].name).toBe("old.dm4");
    expect(useViewer.getState().status).toContain("rename failed");
  });
});
