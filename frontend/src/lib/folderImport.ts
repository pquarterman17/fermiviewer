// Folder-import orchestration (PROJECT_WORKFLOW_PLAN.md items 2-3): turn
// /api/session/open-folder's response into named ImageGroups.
//
// The pure SEEDING RULES below own the group-shaping decision — default is
// one ImageGroup per backend-returned folder group (named after the
// folder), unless the caller asks to merge everything into one — and are
// deliberately synchronous/side-effect-free so they're unit-tested without
// mocking fetch (folderImport.test.ts). `importFolders` at the bottom is
// the only part that touches the network or the store.

import {
  isFourDMeta,
  openFolders,
  type FolderGroupResult,
  type FourDMeta,
  type ImageMeta,
} from "./api";
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

/** Import one or more on-disk folders: fetch the backend's per-folder
 *  groups, ingest every 2D image into the library, seed an ImageGroup per
 *  the rules above (or one merged group), and report the outcome via the
 *  store's existing status mechanism.
 *
 *  4D-STEM entries a folder may contain (`FourDMeta`) can't be ingested
 *  into `images`/grouped yet (store/viewerSession.ts's `ingestImages`
 *  already drops them for the same reason on every other open path), so a
 *  group left with none after that filter reports the same way an
 *  actually-empty folder does, rather than creating a group with zero
 *  effective members. */
export async function importFolders(
  paths: string[],
  opts: { merge?: boolean } = {},
): Promise<void> {
  if (paths.length === 0) return;
  const res = await openFolders(paths);
  const { specs, emptyFolders } = seedGroupSpecs(res.groups, opts.merge ?? false);

  const specImages = specs.map((spec) => ({
    name: spec.name,
    images: images2DOf(spec.images),
  }));
  const allImages2D = specImages.flatMap((g) => g.images);

  const s = useViewer.getState();
  if (allImages2D.length > 0) s.ingest(allImages2D);

  let groupCount = 0;
  const unusable: string[] = [];
  for (const g of specImages) {
    if (g.images.length === 0) {
      unusable.push(g.name);
      continue;
    }
    s.createGroup(g.images.map((m) => m.id), g.name);
    groupCount++;
  }

  s.setStatus(
    summarizeImport({
      groupCount,
      imageCount: allImages2D.length,
      skipped: res.skipped,
      truncated: res.truncated,
      emptyFolders: [...emptyFolders, ...unusable],
    }),
  );
}
