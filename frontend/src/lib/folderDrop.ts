// Folder drag-and-drop (PROJECT_WORKFLOW_PLAN.md item 4).
//
// A dropped directory hands the browser a DataTransferItem —
// `.webkitGetAsEntry()` resolves it to an opaque FileSystemEntry you can
// read file CONTENT through, never a server-side filesystem path: no
// browser exposes one for a drop (sandboxed by design), and this app's
// Tauri shell buys no extra native drop API either, because its window
// navigates to a plain http://127.0.0.1 URL rather than the tauri://
// origin JS-side Tauri APIs require (see src-tauri/Cargo.toml's comment
// on why that IPC grant is deliberately avoided). So a dropped folder
// cannot be handed to /session/open-folder (routes/folders.py), which
// scans a real on-disk path.
//
// Instead: walk the dropped entries client-side with the SAME G3 rules
// io/folder_scan.py implements server-side (own loose files → one group;
// each first-level subfolder, recursively flattened → one group; the
// same combined 500-file cap), upload the flattened file list through the
// existing /session/upload route (a byte upload needs no path), then hand
// the result to lib/folderImport.ts's `applyFolderImport` — the exact
// same seeding/nesting/status tail `importFolders` uses. One set of
// rules, two ways in.

import {
  applyFolderImport,
  type FolderRootInfo,
  type ImportSummary,
} from "./folderImport";
import { supportedExtensions, uploadFiles, type ImageMeta } from "./api";
import type { FolderGroupResult } from "./api/folders";

// Mirrors io/folder_scan.py's `_MAX_FILES`. Nothing to literally share
// across the Python/TS boundary, so this is a second declaration of the
// same policy value, kept honest by test_api_folders.py / folderDrop.test.ts
// both pinning 500.
const MAX_FILES = 500;

interface WalkedGroup {
  name: string;
  files: File[];
}

interface WalkResult {
  groups: WalkedGroup[];
  skipped: number;
  roots: FolderRootInfo[];
  truncated: boolean;
}

/** True iff `item` is a dropped directory (vs. a plain file) — the signal
 *  App.tsx's drop handler uses to route a drop through the folder-import
 *  path here instead of the unchanged plain-file `openFiles` path. */
export function isDirectoryItem(
  item: DataTransferItem,
): FileSystemDirectoryEntry | null {
  if (item.kind !== "file") return null;
  const entry = item.webkitGetAsEntry?.();
  return entry && entry.isDirectory ? (entry as FileSystemDirectoryEntry) : null;
}

/** Every dropped directory entry among `items` — a drop with at least one
 *  of these routes through `importDroppedFolders` rather than `openFiles`,
 *  even if the same drop also carried loose files (those are ignored: G3
 *  has no notion of a "containing folder" for files with no shared parent
 *  entry, unlike a dialog-imported path or a dropped folder's own loose
 *  children — both of which DO have one). */
export function droppedDirectoryEntries(
  items: DataTransferItemList | DataTransferItem[],
): FileSystemDirectoryEntry[] {
  const out: FileSystemDirectoryEntry[] = [];
  for (const item of Array.from(items)) {
    const dir = isDirectoryItem(item);
    if (dir) out.push(dir);
  }
  return out;
}

function extOf(name: string): string {
  const i = name.lastIndexOf(".");
  return i === -1 ? "" : name.slice(i).toLowerCase();
}

const byNameCI = (a: FileSystemEntry, b: FileSystemEntry) =>
  a.name.toLowerCase() < b.name.toLowerCase()
    ? -1
    : a.name.toLowerCase() > b.name.toLowerCase()
      ? 1
      : 0;

/** `reader.readEntries()` only returns ONE batch per call — the spec
 *  requires calling it repeatedly until it resolves empty to see every
 *  entry in a large directory. */
function readAllEntries(
  reader: FileSystemDirectoryReader,
): Promise<FileSystemEntry[]> {
  return new Promise((resolve, reject) => {
    const all: FileSystemEntry[] = [];
    const readBatch = () => {
      reader.readEntries((batch) => {
        if (batch.length === 0) {
          resolve(all);
          return;
        }
        all.push(...batch);
        readBatch();
      }, reject);
    };
    readBatch();
  });
}

function entryToFile(entry: FileSystemFileEntry): Promise<File> {
  return new Promise((resolve, reject) => entry.file(resolve, reject));
}

/** Every supported file anywhere under `dir`, depth-first in the same
 *  case-insensitive name order at each level — the "flatten" side of G3:
 *  files nested arbitrarily deep inside a first-level subfolder all land
 *  in that subfolder's one group. Mirrors io/folder_scan.py's
 *  `_collect_recursive`. */
async function collectRecursive(
  dir: FileSystemDirectoryEntry,
  exts: ReadonlySet<string>,
): Promise<{ files: File[]; skipped: number }> {
  const entries = (await readAllEntries(dir.createReader())).sort(byNameCI);
  const files: File[] = [];
  let skipped = 0;
  for (const entry of entries) {
    if (entry.isDirectory) {
      const sub = await collectRecursive(
        entry as FileSystemDirectoryEntry,
        exts,
      );
      files.push(...sub.files);
      skipped += sub.skipped;
      continue;
    }
    const file = await entryToFile(entry as FileSystemFileEntry);
    if (exts.has(extOf(file.name))) files.push(file);
    else skipped++;
  }
  return { files, skipped };
}

/** One dropped folder, scanned like io/folder_scan.py's `_scan_selected`:
 *  its own loose supported files become a group named after it, then
 *  each first-level subfolder (recursively flattened) becomes its own
 *  group, named after the subfolder, in name order. */
async function scanDroppedFolder(
  root: FileSystemDirectoryEntry,
  exts: ReadonlySet<string>,
): Promise<{ groups: WalkedGroup[]; skipped: number }> {
  const entries = (await readAllEntries(root.createReader())).sort(byNameCI);
  const groups: WalkedGroup[] = [];
  const loose: File[] = [];
  const subfolders: FileSystemDirectoryEntry[] = [];
  let skipped = 0;
  for (const entry of entries) {
    if (entry.isDirectory) {
      subfolders.push(entry as FileSystemDirectoryEntry);
      continue;
    }
    const file = await entryToFile(entry as FileSystemFileEntry);
    if (exts.has(extOf(file.name))) loose.push(file);
    else skipped++;
  }
  if (loose.length > 0) groups.push({ name: root.name, files: loose });
  for (const sub of subfolders) {
    const collected = await collectRecursive(sub, exts);
    skipped += collected.skipped;
    if (collected.files.length > 0) {
      groups.push({ name: sub.name, files: collected.files });
    }
  }
  return { groups, skipped };
}

/** Scan every dropped root folder, then apply the SAME combined 500-file
 *  cap io/folder_scan.py's `_apply_cap` applies server-side (item 5), so
 *  a drag-dropped import is capped the same way a dialog-imported one is
 *  — one shared policy regardless of entry point. Tracks each root's own
 *  pre-cap group count so `seedProjectSpecs` (item 27) can tell a flat
 *  drop from a folder-of-folders drop, adjusting it down if the cap cut
 *  into or past that root — mirrors `_apply_cap`'s root-count trimming. */
async function walkDroppedFolders(
  roots: FileSystemDirectoryEntry[],
  exts: ReadonlySet<string>,
): Promise<WalkResult> {
  const allGroups: WalkedGroup[] = [];
  const rootsPre: FolderRootInfo[] = [];
  let skipped = 0;
  for (const root of roots) {
    const scanned = await scanDroppedFolder(root, exts);
    allGroups.push(...scanned.groups);
    rootsPre.push({ name: root.name, groupCount: scanned.groups.length });
    skipped += scanned.skipped;
  }

  const total = allGroups.reduce((n, g) => n + g.files.length, 0);
  if (total <= MAX_FILES) {
    return { groups: allGroups, skipped, roots: rootsPre, truncated: false };
  }

  const capped: WalkedGroup[] = [];
  let remaining = MAX_FILES;
  for (const g of allGroups) {
    if (remaining <= 0) break;
    const files = g.files.slice(0, remaining);
    remaining -= files.length;
    capped.push({ name: g.name, files });
  }
  const kept = capped.length;
  let consumed = 0;
  const roots2 = rootsPre.map((r) => {
    const adjusted = Math.max(0, Math.min(r.groupCount, kept - consumed));
    consumed += r.groupCount;
    return { name: r.name, groupCount: adjusted };
  });
  return { groups: capped, skipped, roots: roots2, truncated: true };
}

/** Zip uploaded ImageMeta back into the group shape `applyFolderImport`
 *  expects — `uploadFiles` preserves request order (routes/images.py's
 *  `/session/upload` appends one meta per file in a single ordered pass),
 *  so a running offset by group size is enough. */
function rechunk(
  groups: WalkedGroup[],
  metas: ImageMeta[],
): FolderGroupResult[] {
  const out: FolderGroupResult[] = [];
  let i = 0;
  for (const g of groups) {
    out.push({ name: g.name, images: metas.slice(i, i + g.files.length) });
    i += g.files.length;
  }
  return out;
}

/** Import one or more folders dropped onto the window. There is no
 *  server-side path to hand /session/open-folder, so every supported
 *  file's bytes are read and uploaded in one batch instead, then the
 *  result is fed through `applyFolderImport` — the exact tail
 *  `importFolders` (the Import-dialog path) uses, so a dropped folder
 *  and a dialog-imported one behave identically once their bytes are in
 *  the library. Returns null if `roots` is empty (nothing to do — the
 *  caller only calls this when `droppedDirectoryEntries` found at least
 *  one) or if none of the dropped files had a supported extension. */
export async function importDroppedFolders(
  roots: FileSystemDirectoryEntry[],
): Promise<ImportSummary | null> {
  if (roots.length === 0) return null;
  const exts = new Set(await supportedExtensions());
  const walked = await walkDroppedFolders(roots, exts);
  const flatFiles = walked.groups.flatMap((g) => g.files);
  const metas = flatFiles.length > 0 ? await uploadFiles(flatFiles) : [];
  return applyFolderImport({
    groups: rechunk(walked.groups, metas),
    skipped: walked.skipped,
    truncated: walked.truncated,
    roots: walked.roots,
  });
}
