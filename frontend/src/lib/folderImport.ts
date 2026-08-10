// Folder-import orchestration (PROJECT_WORKFLOW_PLAN.md items 2-3, 4, 27):
// turn /api/session/open-folder's response — or a drag-and-drop-built
// equivalent (lib/folderDrop.ts, item 4) — into named ImageGroups, nesting
// per-folder samples under a parent project when the import found sample
// subfolders (item 27).
//
// The pure SEEDING RULES below own the group-shaping decision — default is
// one ImageGroup per backend-returned folder group (named after the
// folder), unless the caller asks to merge everything into one — and are
// deliberately synchronous/side-effect-free so they're unit-tested without
// mocking fetch (folderImport.test.ts). `applyFolderImport` is the ONE
// shared tail (ingest → create groups → nest projects → report) both
// `importFolders` (real on-disk paths) and lib/folderDrop.ts's
// `importDroppedFolders` (uploaded bytes, no server-side path available)
// feed into — one set of rules regardless of how the groups were found.

import {
  isFourDMeta,
  openFolders,
  type FolderGroupResult,
  type FourDMeta,
  type ImageMeta,
} from "./api";
import type { FolderRootResult } from "./api/folders";
import { useFolderImportNotice } from "../store/folderImportNotice";
import { useViewer } from "../store/viewer";

// ── pure seeding rules ──────────────────────────────────────────────────

/** One group ready to hand to `createGroup(ids, name)`. */
export interface GroupSpec {
  name: string;
  images: (ImageMeta | FourDMeta)[];
}

export interface SeedResult {
  specs: GroupSpec[];
  /** Names of backend groups that carried zero images — the scanner
   *  (io/folder_scan.py) never emits one, but this stays defensive rather
   *  than trusting that invariant silently. */
  emptyFolders: string[];
}

/** Up to this many folder names are spelled out in a merged group's name
 *  before falling back to "+ N more" (mergedGroupName). */
const MAX_NAMED_IN_MERGE = 3;

/** Group-seeding rules (item 3): one folder = one group; N folders = N
 *  groups, each named after its folder; the merge flag collapses every
 *  image from every returned group into a single group instead. A group
 *  with no images produces no group and is reported by name so it can be
 *  surfaced via the status bar instead of vanishing silently. */
export function seedGroupSpecs(
  groups: FolderGroupResult[],
  merge: boolean,
): SeedResult {
  const nonEmpty = groups.filter((g) => g.images.length > 0);
  const emptyFolders = groups
    .filter((g) => g.images.length === 0)
    .map((g) => g.name);

  if (nonEmpty.length === 0) return { specs: [], emptyFolders };

  if (merge) {
    return {
      specs: [
        {
          name: mergedGroupName(nonEmpty),
          images: nonEmpty.flatMap((g) => g.images),
        },
      ],
      emptyFolders,
    };
  }

  const taken = new Set<string>();
  const specs = nonEmpty.map((g) => {
    const name = dedupeGroupName(g.name, taken);
    taken.add(name);
    return { name, images: g.images };
  });
  return { specs, emptyFolders };
}

/** Suffix `name` with " (2)", " (3)", … until it's not already in `taken`
 *  — so two folders sharing a basename (two different "data" subfolders
 *  under different parents) become two distinguishable groups instead of
 *  one silently swallowing the other's images under an identical label. */
export function dedupeGroupName(
  name: string,
  taken: ReadonlySet<string>,
): string {
  if (!taken.has(name)) return name;
  let n = 2;
  while (taken.has(`${name} (${n})`)) n++;
  return `${name} (${n})`;
}

/** Deterministic name for a merge-mode group: the folder names it drew
 *  from, joined, truncated so merging many folders doesn't produce an
 *  unreadable label. */
export function mergedGroupName(groups: FolderGroupResult[]): string {
  const names = groups.map((g) => g.name);
  if (names.length <= MAX_NAMED_IN_MERGE) return names.join(" + ");
  const shown = names.slice(0, MAX_NAMED_IN_MERGE).join(" + ");
  return `${shown} + ${names.length - MAX_NAMED_IN_MERGE} more`;
}

// ── project nesting (item 27: import seeds projects) ────────────────────

/** One requested directory's own name and how many of the scan's `groups`
 *  it produced — the camelCase mirror of api/folders.ts's
 *  FolderRootResult (and of lib/folderDrop.ts's client-side walk, which
 *  has no backend response to read this from). */
export interface FolderRootInfo {
  name: string;
  groupCount: number;
}

/** A parent project to create: its name, and the (already-deduped) names
 *  of the sample specs that become its children via setGroupParent. */
export interface ProjectSpec {
  name: string;
  childNames: string[];
}

export interface ProjectSeedResult extends SeedResult {
  projects: ProjectSpec[];
}

/** Extends `seedGroupSpecs` with project nesting (item 27): a requested
 *  directory that produced MORE THAN ONE group (a folder holding sample
 *  subfolders) gets a parent project named after it, with those groups as
 *  children. A flat directory (0 or 1 usable group, after dropping any
 *  that turned out empty) produces no project — item 27's "the simple
 *  case is unchanged" — and merge mode never nests, since it already
 *  collapses everything to one group.
 *
 *  A project's name is deduped against every sample name AND every other
 *  project name in this same import (dedupeGroupName), which matters when
 *  a directory has BOTH loose images and subfolders: its loose-image
 *  child is named after the directory itself (seedGroupSpecs), so the
 *  project gets " (2)" rather than silently colliding with its own child. */
export function seedProjectSpecs(
  groups: FolderGroupResult[],
  roots: FolderRootInfo[],
  merge: boolean,
): ProjectSeedResult {
  const base = seedGroupSpecs(groups, merge);
  if (merge || roots.length === 0) return { ...base, projects: [] };

  // seedGroupSpecs (non-merge) maps 1:1 over the nonEmpty subset of
  // `groups`, preserving order — replay that same filter to recover which
  // final (deduped) spec name each ORIGINAL group index landed on, or null
  // if it was dropped as empty.
  const specNameByIndex: (string | null)[] = [];
  let specI = 0;
  for (const g of groups) {
    if (g.images.length === 0) {
      specNameByIndex.push(null);
    } else {
      specNameByIndex.push(base.specs[specI]?.name ?? null);
      specI++;
    }
  }

  const taken = new Set(base.specs.map((s) => s.name));
  const projects: ProjectSpec[] = [];
  let offset = 0;
  for (const root of roots) {
    const childNames = specNameByIndex
      .slice(offset, offset + root.groupCount)
      .filter((n): n is string => n !== null);
    offset += root.groupCount;
    if (childNames.length > 1) {
      const name = dedupeGroupName(root.name, taken);
      taken.add(name);
      projects.push({ name, childNames });
    }
  }
  return { ...base, projects };
}

// ── status-bar summary ──────────────────────────────────────────────────

export interface ImportSummary {
  groupCount: number;
  imageCount: number;
  skipped: number;
  truncated: boolean;
  emptyFolders: string[];
}

/** Render one line for the existing status mechanism (setStatus), e.g.
 *  "opened 40 images in 2 groups — skipped 3 unsupported". */
export function summarizeImport(s: ImportSummary): string {
  const head = `opened ${s.imageCount} image${s.imageCount === 1 ? "" : "s"} in ${
    s.groupCount
  } group${s.groupCount === 1 ? "" : "s"}`;
  const notes: string[] = [];
  if (s.skipped > 0) notes.push(`skipped ${s.skipped} unsupported`);
  if (s.truncated) notes.push("truncated at 500 files");
  if (s.emptyFolders.length > 0) {
    notes.push(`no supported images in ${s.emptyFolders.join(", ")}`);
  }
  return notes.length > 0 ? `${head} — ${notes.join("; ")}` : head;
}

// ── async orchestration ─────────────────────────────────────────────────

const images2DOf = (images: (ImageMeta | FourDMeta)[]): ImageMeta[] =>
  images.filter((m): m is ImageMeta => !isFourDMeta(m));

/** Anything shaped like an /session/open-folder response — the real one
 *  (openFolders), or lib/folderDrop.ts's client-side-walked equivalent
 *  built from uploaded bytes (no server-side path exists for a dropped
 *  folder to hand the real endpoint). `roots` is optional so a caller
 *  with no root-boundary info (there is none today, but keeps this from
 *  becoming a breaking change if one ever calls it without) still nests
 *  nothing rather than throwing. */
export interface FolderScanLike {
  groups: FolderGroupResult[];
  skipped: number;
  truncated: boolean;
  roots?: FolderRootInfo[];
}

/** The ONE shared tail: ingest every 2D image, create a sample group per
 *  seeded spec, nest per-directory sample groups under a new parent
 *  project where item 27 applies, and report the outcome — both via the
 *  existing status-bar mechanism (setStatus) and the persistent
 *  folder-import notice (store/folderImportNotice.ts) that
 *  FolderImportBanner.tsx renders unmissably regardless of whether the
 *  triggering dialog is still open (item 5).
 *
 *  4D-STEM entries a folder may contain (`FourDMeta`) can't be ingested
 *  into `images`/grouped yet (store/viewerSession.ts's `ingestImages`
 *  already drops them for the same reason on every other open path), so a
 *  group left with none after that filter reports the same way an
 *  actually-empty folder does, rather than creating a group with zero
 *  effective members. */
export async function applyFolderImport(
  res: FolderScanLike,
  opts: { merge?: boolean } = {},
): Promise<ImportSummary> {
  const merge = opts.merge ?? false;
  const { specs, projects, emptyFolders } = seedProjectSpecs(
    res.groups,
    res.roots ?? [],
    merge,
  );

  const specImages = specs.map((spec) => ({
    name: spec.name,
    images: images2DOf(spec.images),
  }));
  const allImages2D = specImages.flatMap((g) => g.images);

  const s = useViewer.getState();
  if (allImages2D.length > 0) s.ingest(allImages2D);

  let groupCount = 0;
  const unusable: string[] = [];
  const idByName = new Map<string, string>();
  for (const g of specImages) {
    if (g.images.length === 0) {
      unusable.push(g.name);
      continue;
    }
    const id = s.createGroup(g.images.map((m) => m.id), g.name);
    if (id) idByName.set(g.name, id);
    groupCount++;
  }

  for (const project of projects) {
    const childIds = project.childNames
      .map((n) => idByName.get(n))
      .filter((id): id is string => !!id);
    if (childIds.length === 0) continue; // every child turned out unusable
    const projectId = s.createEmptyGroup(project.name);
    for (const childId of childIds) s.setGroupParent(childId, projectId);
  }

  const summary: ImportSummary = {
    groupCount,
    imageCount: allImages2D.length,
    skipped: res.skipped,
    truncated: res.truncated,
    emptyFolders: [...emptyFolders, ...unusable],
  };
  s.setStatus(summarizeImport(summary));
  useFolderImportNotice.getState().set(summary);
  return summary;
}

/** Import one or more on-disk folders (the Import-dialog path, items 2-3):
 *  fetch the backend's per-folder groups and hand them to the shared tail
 *  above. Returns null without any network call when `paths` is empty. */
export async function importFolders(
  paths: string[],
  opts: { merge?: boolean } = {},
): Promise<ImportSummary | null> {
  if (paths.length === 0) return null;
  const res = await openFolders(paths);
  return applyFolderImport(
    {
      groups: res.groups,
      skipped: res.skipped,
      truncated: res.truncated,
      // optional-chained: older mocks in folderImport.test.ts resolve
      // without a `roots` field, and must keep working unmodified.
      roots: res.roots?.map(toRootInfo) ?? [],
    },
    opts,
  );
}

function toRootInfo(r: FolderRootResult): FolderRootInfo {
  return { name: r.name, groupCount: r.group_count };
}
