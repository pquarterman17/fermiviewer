// folderDrop.ts (PROJECT_WORKFLOW_PLAN.md item 4): the entry-walking logic
// is exercised against fake FileSystemEntry objects (jsdom implements
// neither the File and Directory Entries API nor webkitGetAsEntry), and
// the network boundary (uploadFiles) plus the shared import tail
// (applyFolderImport) are mocked — their own behavior is covered by
// folderImport.test.ts.

import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    supportedExtensions: vi.fn(),
    uploadFiles: vi.fn(),
  };
});
vi.mock("./folderImport", () => ({
  applyFolderImport: vi.fn(),
}));

import type { ImageMeta } from "./api/core";
import { supportedExtensions, uploadFiles } from "./api";
import { applyFolderImport } from "./folderImport";
import {
  droppedDirectoryEntries,
  importDroppedFolders,
  isDirectoryItem,
} from "./folderDrop";

// ── fake File and Directory Entries API ─────────────────────────────────

function fakeFileEntry(name: string): FileSystemFileEntry {
  return {
    name,
    isFile: true,
    isDirectory: false,
    file: (success: (f: File) => void) => success(new File([""], name)),
  } as unknown as FileSystemFileEntry;
}

/** A directory entry whose reader hands back `children` on the FIRST
 *  `readEntries` call and an empty array on every call after — mirrors the
 *  real API's "call repeatedly until empty" contract (readAllEntries). */
function fakeDirEntry(
  name: string,
  children: FileSystemEntry[],
): FileSystemDirectoryEntry {
  let consumed = false;
  return {
    name,
    isFile: false,
    isDirectory: true,
    createReader: () => ({
      readEntries: (success: (entries: FileSystemEntry[]) => void) => {
        if (consumed) {
          success([]);
          return;
        }
        consumed = true;
        success(children);
      },
    }),
  } as unknown as FileSystemDirectoryEntry;
}

function fakeItem(entry: FileSystemEntry | null): DataTransferItem {
  return {
    kind: "file",
    webkitGetAsEntry: () => entry,
  } as unknown as DataTransferItem;
}

function img(id: string): ImageMeta {
  return { id, name: `${id}.tif`, kind: "image" } as unknown as ImageMeta;
}

// ── routing: directory vs. plain file ───────────────────────────────────

describe("isDirectoryItem / droppedDirectoryEntries", () => {
  it("returns the entry for a directory item", () => {
    const dir = fakeDirEntry("StudyA", []);
    expect(isDirectoryItem(fakeItem(dir))).toBe(dir);
  });

  it("returns null for a plain file item", () => {
    expect(isDirectoryItem(fakeItem(fakeFileEntry("a.png")))).toBeNull();
  });

  it("returns null for a non-file item (e.g. dragged text)", () => {
    const textItem = { kind: "string" } as unknown as DataTransferItem;
    expect(isDirectoryItem(textItem)).toBeNull();
  });

  it("a file-only drop yields no directory entries", () => {
    const items = [fakeItem(fakeFileEntry("a.png")), fakeItem(fakeFileEntry("b.png"))];
    expect(droppedDirectoryEntries(items)).toEqual([]);
  });

  it("a drop with at least one folder yields its directory entry", () => {
    const dir = fakeDirEntry("StudyA", []);
    const items = [fakeItem(fakeFileEntry("loose.png")), fakeItem(dir)];
    expect(droppedDirectoryEntries(items)).toEqual([dir]);
  });
});

// ── importDroppedFolders: walk + upload + hand off to applyFolderImport ─

describe("importDroppedFolders", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(supportedExtensions).mockResolvedValue([".png"]);
  });

  it("returns null and uploads nothing for an empty root list", async () => {
    const result = await importDroppedFolders([]);
    expect(result).toBeNull();
    expect(uploadFiles).not.toHaveBeenCalled();
  });

  it("a flat dropped folder becomes one group named after it", async () => {
    const dir = fakeDirEntry("StudyA", [
      fakeFileEntry("a.png"),
      fakeFileEntry("b.png"),
    ]);
    vi.mocked(uploadFiles).mockResolvedValue([img("a"), img("b")]);

    await importDroppedFolders([dir]);

    expect(uploadFiles).toHaveBeenCalledTimes(1);
    const uploaded = vi.mocked(uploadFiles).mock.calls[0][0] as File[];
    expect(uploaded.map((f) => f.name)).toEqual(["a.png", "b.png"]);

    expect(applyFolderImport).toHaveBeenCalledWith({
      groups: [{ name: "StudyA", images: [img("a"), img("b")] }],
      skipped: 0,
      truncated: false,
      roots: [{ name: "StudyA", groupCount: 1 }],
    });
  });

  it("a folder of subfolders becomes one group per subfolder (G3, item 27's shape)", async () => {
    const dir = fakeDirEntry("StudyA", [
      fakeDirEntry("sub1", [fakeFileEntry("a.png")]),
      fakeDirEntry("sub2", [fakeFileEntry("b.png")]),
    ]);
    vi.mocked(uploadFiles).mockResolvedValue([img("a"), img("b")]);

    await importDroppedFolders([dir]);

    expect(applyFolderImport).toHaveBeenCalledWith({
      groups: [
        { name: "sub1", images: [img("a")] },
        { name: "sub2", images: [img("b")] },
      ],
      skipped: 0,
      truncated: false,
      roots: [{ name: "StudyA", groupCount: 2 }],
    });
  });

  it("flattens files nested arbitrarily deep into their first-level subfolder", async () => {
    const dir = fakeDirEntry("StudyA", [
      fakeDirEntry("sub1", [
        fakeFileEntry("shallow.png"),
        fakeDirEntry("deeper", [fakeFileEntry("deep.png")]),
      ]),
    ]);
    vi.mocked(uploadFiles).mockResolvedValue([img("a"), img("b")]);

    await importDroppedFolders([dir]);

    const call = vi.mocked(applyFolderImport).mock.calls[0][0];
    expect(call.groups).toHaveLength(1);
    expect(call.groups[0].name).toBe("sub1");
  });

  it("counts unsupported files as skipped rather than uploading them", async () => {
    const dir = fakeDirEntry("StudyA", [
      fakeFileEntry("a.png"),
      fakeFileEntry("notes.txt"),
    ]);
    vi.mocked(uploadFiles).mockResolvedValue([img("a")]);

    await importDroppedFolders([dir]);

    const uploaded = vi.mocked(uploadFiles).mock.calls[0][0] as File[];
    expect(uploaded.map((f) => f.name)).toEqual(["a.png"]);
    const call = vi.mocked(applyFolderImport).mock.calls[0][0];
    expect(call.skipped).toBe(1);
  });

  it("multiple dropped folders: each is its own root", async () => {
    const dirA = fakeDirEntry("A", [fakeFileEntry("a.png")]);
    const dirB = fakeDirEntry("B", [
      fakeDirEntry("sub1", [fakeFileEntry("b.png")]),
      fakeDirEntry("sub2", [fakeFileEntry("c.png")]),
    ]);
    vi.mocked(uploadFiles).mockResolvedValue([img("a"), img("b"), img("c")]);

    await importDroppedFolders([dirA, dirB]);

    const call = vi.mocked(applyFolderImport).mock.calls[0][0];
    expect(call.roots).toEqual([
      { name: "A", groupCount: 1 },
      { name: "B", groupCount: 2 },
    ]);
  });

  it("caps the combined file count at 500 and flags truncated, adjusting root counts", async () => {
    const manyFiles = Array.from({ length: 510 }, (_, i) =>
      fakeFileEntry(`img_${i}.png`),
    );
    const dir = fakeDirEntry("Big", manyFiles);
    vi.mocked(uploadFiles).mockResolvedValue(
      Array.from({ length: 500 }, (_, i) => img(`i${i}`)),
    );

    await importDroppedFolders([dir]);

    const uploaded = vi.mocked(uploadFiles).mock.calls[0][0] as File[];
    expect(uploaded).toHaveLength(500);
    const call = vi.mocked(applyFolderImport).mock.calls[0][0];
    expect(call.truncated).toBe(true);
    expect(call.roots).toEqual([{ name: "Big", groupCount: 1 }]);
  });

  it("does not call uploadFiles when every dropped file is unsupported", async () => {
    const dir = fakeDirEntry("StudyA", [fakeFileEntry("readme.txt")]);

    await importDroppedFolders([dir]);

    expect(uploadFiles).not.toHaveBeenCalled();
    const call = vi.mocked(applyFolderImport).mock.calls[0][0];
    expect(call.groups).toEqual([]);
    expect(call.skipped).toBe(1);
  });
});
