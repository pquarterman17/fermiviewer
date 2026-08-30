// The viewer store's state + action contract — split from viewer.ts
// (repo-health #33). Types only: the implementation lives in viewer.ts,
// the session restore/persist machinery in viewerSession.ts.

import type {
  ImageMeta,
  PersistedResultRecord,
  ProjectRegions,
  RegionWorkspaceUi,
  ProjectPayloadMode,
  RoiStats,
  UnavailableImage,
} from "../lib/api";
import type { TiltSettings } from "../lib/geometry";
import type { ComparePane, GroupParams, ImageGroup } from "../lib/groups";
import type { DisplayUnit } from "../lib/lengthUnits";
import type {
  CaptureMode,
  ColorbarSide,
  CompareMode,
  Display,
  HistoryStep,
  LayersOverlayState,
  ListView,
  Measure,
  MeasureKind,
  OverlayStyle,
  SavedRoi,
  ScaleBarState,
  SelectGesture,
  Theme,
  Accent,
  Density,
  ToolKind,
  ToolWindowState,
  UndoEntry,
  View,
  WorkspaceRef,
} from "./viewerTypes";

export interface ViewerState {
  // library
  order: string[];
  activeId: string | null;
  images: Record<string, ImageMeta>;
  /** Images the open project references but this machine could not find,
   *  keyed by id (ADR 0002 §4). They are NOT in `images` or `order` — there
   *  are no pixels to render — but they keep their name, their sample
   *  membership (`imageGroups`), their parameters and their measurements, and
   *  the server writes their references straight back on the next save.
   *  Narrowed one folder at a time by `locateData`. */
  unavailable: Record<string, UnavailableImage>;
  /** Scientific result records restored from the current .fvp project. */
  persistedResults: PersistedResultRecord[];
  /** Live named analysis regions from ADR 0006. Unlike `measures`, these
   *  are 0-based [row, col] geometry and are server-carried project data. */
  regions: ProjectRegions;
  /** False until the server baseline has loaded; region writes fail closed. */
  regionsLoaded: boolean;
  regionsLoadError: string | null;
  /** Selection/visibility for the region manager and future stage overlay. */
  regionUi: RegionWorkspaceUi;
  selected: string[];
  listView: ListView;
  compareSet: string[] | null;
  compareMode: CompareMode;
  /** Flicker interval in ms (default 600 = ~1.7 Hz, matches MATLAB).
   *  Exposed as a user control (audit #15). */
  compareFlickerMs: number;
  /** Explicit A/B slot override: [indexA, indexB] into compareSet
   *  (null = cycle the full set, original behaviour).  Audit #15. */
  compareAB: [number, number] | null;
  // ── side-by-side compare: an N-pane grid (compareMode "sidebyside") ──
  /** Each grid cell: the image it shows + an optional bound group. Default
   *  grid is 1×2, both panes unbound → original two-pane behaviour. */
  sbsPanes: ComparePane[];
  /** Grid shape; sbsPanes.length always equals sbsRows*sbsCols. */
  sbsRows: number;
  sbsCols: number;
  /** Index into sbsPanes the ←/→ keys + ◀▶ buttons drive; others freeze. */
  sbsActive: number;
  /** Link zoom level across all panes (default true; toggle to unlink). */
  sbsLinked: boolean;
  // ── named image groups (reusable, persisted) ──
  /** Ordered named groups built from multi-selections; bind one to a pane.
   *  A group carrying params/parent is a sample or project (ADR 0002 §5). */
  imageGroups: ImageGroup[];
  // monotonic counter bumped on every ingestDerived — a lineage signal that
  // lets views like Live FFT re-fetch when a new derived image is produced
  // without subscribing to the whole image map (Quick-Wins #7)
  derivedTick: number;
  // per-image view, persisted (localStorage "fv_views")
  views: Record<string, View>;
  // per-image display pipeline (window/gamma/colormap)
  display: Record<string, Display>;
  // WS4d: per-image non-destructive edit history + the current-step cursor
  history: Record<string, HistoryStep[]>;
  historyAt: Record<string, number>;
  // measurements, per image; selection is a measure id
  measures: Record<string, Measure[]>;
  selectedMeasure: string | null;
  roiStats: Record<string, RoiStats>;
  // undo/redo (Edit menu)
  undoStack: UndoEntry[];
  redoStack: UndoEntry[];
  // display chrome
  theme: Theme;
  accent: Accent;
  density: Density;
  overlay: OverlayStyle; // persisted "fv_overlay"
  // per-image scale bar position/size overrides
  scaleBars: Record<string, ScaleBarState>;
  // per-image tilt-correction settings (#34); absent = off
  tilts: Record<string, TiltSettings>;
  // per-image stack frame index (0-based; only relevant for spectrum_image)
  stackFrames: Record<string, number>;
  /** Named saved ROIs per image — keyed by image id.  Persisted in session
   *  client_state["savedRois"] so save/load round-trips them (Tier-2 #5). */
  savedRois: Record<string, SavedRoi[]>;
  /** fixed-zoom dimensions in image pixels (A2 capture mode) */
  fixedZoomW: number;
  fixedZoomH: number;
  // tools
  captureMode: CaptureMode;
  // spectrum-navigation pixel (1-based [row, col]) picked on the main stage in
  // specnav mode; the EELS/EDS workshops watch it to drive their spectrum (#10)
  specnavPixel: [number, number] | null;
  // 4D-STEM probe pixel (1-based [row, col]) picked on the main stage in
  // fourdnav mode — same shape/convention as specnavPixel; the FourD
  // workshop watches it (via useFourDNavProbeSync) to move the probe (#14)
  fourdNavPixel: [number, number] | null;
  layersOverlay: LayersOverlayState | null;
  layersEdit: boolean;                 // stage interface-editing mode
  layersEditReq: number[] | null;      // positions requested by a stage edit
  layersFocusReq: number | null;       // interface index clicked on the stage
  panTool: boolean;
  profileWidth: number;  // ⊥ averaging width (px) for profile captures
  profileReduce: "mean" | "sum"; // box/profile reduction mode (item #49)
  toolsLayout: "cards" | "unified"; // inspector tools layout (persisted pref)
  // chrome
  leftCol: boolean;
  rightCol: boolean;
  minimap: boolean;
  colorbar: boolean;
  colorbarSide: ColorbarSide; // persisted "colorbarSide" pref
  scaleBarVisible: boolean;
  cmdk: boolean;
  shorts: boolean;
  radial: { x: number; y: number } | null;
  tools: ToolWindowState[]; // open workshop windows (handoff §6)
  exportOpen: boolean;
  batchOpen: boolean;
  calibOpen: boolean;
  metaOpen: boolean;
  prefsOpen: boolean;
  galleryOpen: boolean;
  /** Whether the launch-folder Open dialog is showing. */
  folderOpen: boolean;
  /** The folder the app was launched from + its supported images, so the
   *  Open dialog can default there. null until fetched / when none set. */
  launchContext: { dir: string | null; files: { name: string; path: string }[] } | null;
  status: string;
  currentWorkspace: WorkspaceRef | null;
  /** The `.fvp` this session is working in, once one has been opened or
   *  saved. Null for a session that has only ever opened loose images. */
  currentProject: { path: string; name: string | null } | null;

  openPaths: (paths: string[]) => Promise<void>;
  openFiles: (files: FileList | File[]) => Promise<void>;
  ingest: (metas: ImageMeta[]) => void;
  /** Write the session as a `.fvp`. `"light"` references source pixels and
   *  embeds derived images (Save Project); `"bundle"` embeds everything so
   *  the file needs no source folders (Export Project Bundle). */
  saveProject: (path: string, mode?: ProjectPayloadMode) => Promise<void>;
  /** Open a `.fvp`, or a legacy v1 `.json`/`.npz` pair (migrated on load). */
  openProject: (path: string) => Promise<void>;
  /** Re-resolve unavailable images against a folder the user picked.
   *  Invokable at any time and repeatable — different samples may have moved
   *  to different folders. */
  locateData: (root: string) => Promise<void>;
  /** Validate and atomically replace the live named-region workspace. */
  replaceRegions: (regions: ProjectRegions) => Promise<void>;
  /** Seed the server-carried workspace after a browser refresh. No write. */
  hydrateRegions: (regions: ProjectRegions) => void;
  /** Retry the read-only server hydration used on browser startup. */
  refreshRegions: () => Promise<void>;
  selectRegion: (setId: string | null, regionId?: string | null) => void;
  toggleRegionSetVisibility: (setId: string) => void;
  toggleRegionVisibility: (setId: string, regionId: string) => void;
  saveWorkspaceNamed: (name: string) => Promise<void>;
  loadWorkspaceNamed: (slug: string) => Promise<void>;
  setActive: (id: string) => void;
  select: (id: string, gesture: SelectGesture) => void;
  setListView: (v: ListView) => void;
  reorder: (id: string, beforeId: string | null) => void;
  startCompare: (ids: string[]) => void;
  exitCompare: () => void;
  setCompareMode: (m: CompareMode) => void;
  setCompareFlickerMs: (ms: number) => void;
  setCompareAB: (ab: [number, number] | null) => void;
  /** Enter side-by-side compare seeded from the current image (pane 0 =
   *  active, pane 1 = next in order). No pre-selection needed. */
  startSideBySide: () => void;
  /** Enter side-by-side compare seeded for cross-sample stepping (item 26):
   *  pane i is bound to `sampleIds[i]`, all starting at the MATCHED member
   *  index (the active image's position within whichever sample contains
   *  it, else 0) — so arrow keys/◀▶ then walk equivalent frames across
   *  samples. Grid becomes 1×sampleIds.length. No-op (with a status
   *  message) if fewer than 2 ids resolve to a real group. */
  startSampleCompare: (sampleIds: string[]) => void;
  /** Set a pane's image directly (e.g. dropdown pick) and focus it. */
  setPaneImage: (idx: number, id: string) => void;
  /** Bind a named group to a pane (null = unbound → steps all images);
   *  snaps the pane's image to the group's first member if needed. */
  setPaneGroup: (idx: number, groupId: string | null) => void;
  /** Step a pane within its bound group's members by delta (wrapping);
   *  snaps to the first member if the current image isn't in the group. */
  stepPane: (idx: number, delta: 1 | -1) => void;
  /** Focus a pane (the ←/→ keys + ◀▶ buttons drive the focused pane). */
  setActivePane: (idx: number) => void;
  /** Resize the compare grid, preserving existing pane bindings by index. */
  setGrid: (rows: number, cols: number) => void;
  setSbsLinked: (linked: boolean) => void;
  // ── named image groups ──────────────────────────────────────────────
  /** Create a named group from the given image ids; default name `Group N`.
   *  Returns the new group's id, or null if no valid image id was given
   *  (rejected — a group must hold at least one image; see
   *  createEmptyGroup for the one case that doesn't). */
  createGroup: (ids: string[], name?: string) => string | null;
  /** Create an empty-membership group — a project (item 27), which holds
   *  its images only through its sample children via setGroupParent.
   *  Unlike createGroup, an empty member list is never rejected. Returns
   *  the new group's id. */
  createEmptyGroup: (name: string) => string;
  renameGroup: (id: string, name: string) => void;
  /** Delete a group and unbind it from any pane that referenced it. */
  deleteGroup: (id: string) => void;
  /** Replace a group's member list. */
  setGroupMembers: (id: string, ids: string[]) => void;
  /** Replace a group's parameter map wholesale — same semantics as
   *  setGroupMembers, so a single-field edit passes `{ ...g.params, k: v }`.
   *  Values are normalised to what the manifest schema accepts (finite
   *  number / string / boolean, unit forced to string|null). */
  setGroupParams: (id: string, params: GroupParams) => void;
  /** Nest a group under `parentId` (project → sample), or make it a root with
   *  null. No-ops if the group or the parent doesn't exist, or if the move
   *  would create a cycle (which reports via setStatus). */
  setGroupParent: (id: string, parentId: string | null) => void;
  /** Append one open image to a group's members; no-op if it isn't open or is
   *  already a member. */
  addGroupMember: (id: string, imageId: string) => void;
  /** Drop one image from a group's members, keeping the group even if it
   *  empties (an image-less group can be a project). */
  removeGroupMember: (id: string, imageId: string) => void;
  cycleImage: (dir: 1 | -1) => void;
  closeImage: (id: string) => Promise<void>;
  setView: (id: string, view: View) => void;
  setDisplay: (
    id: string,
    patch: Partial<Display>,
    opts?: { silent?: boolean },
  ) => void;
  ingestDerived: (metas: ImageMeta[]) => void;
  /** WS4d: jump the active image's display to a history step (revert or
   *  step forward); moves the cursor without dropping steps. */
  revertHistory: (id: string, index: number) => void;
  pushUndo: (e: UndoEntry) => void;
  undo: () => UndoEntry | null;
  redo: () => UndoEntry | null;
  addMeasure: (imageId: string, m: Omit<Measure, "id">) => string;
  updateMeasure: (
    imageId: string,
    measureId: string,
    pts: Measure["pts"],
    /** Holes-detach fix: when provided (not undefined), REPLACES the
     *  measure's holes field too, in the same update as `pts` — used by
     *  the whole-body translate (MeasureVertexLayer.tsx) so a translated
     *  region's holes move with it instead of staying behind. Omitted or
     *  explicitly undefined leaves the existing holes field untouched. */
    holes?: Measure["holes"],
  ) => void;
  removeMeasure: (imageId: string, measureId: string) => void;
  /** Plan item 4 — DRAW a hole: convert an existing top-level polygon/
   *  lasso measure (`childId`), fully contained by `hostId`, into a
   *  subtracted hole of that host. Undoable, symmetric with removeHole. */
  addHole: (imageId: string, hostId: string, childId: string) => void;
  /** Inverse of addHole: detach one of a region's holes back into its
   *  own top-level polygon measure with a fresh id — a hole is just a
   *  point ring while it lives in `.holes`, so it has no id to restore. */
  removeHole: (imageId: string, hostId: string, holeIndex: number) => void;
  /** Remove the most recently added annotation/measure (audit #11). */
  deleteLastAnnotation: (imageId: string) => void;
  /** Switch the active image to the root ancestor of a derived chain,
   *  restoring the original un-filtered pixels (audit #11).  The server
   *  already holds every ancestor DataStruct for the session; this only
   *  updates the client's activeId pointer. */
  resetToOriginal: (imageId: string) => void;
  setMeasureText: (imageId: string, measureId: string, text: string) => void;
  setMeasureStyle: (
    imageId: string,
    measureId: string,
    patch: Partial<Pick<Measure, "color" | "labelDx" | "labelDy" | "endSymbol">>,
  ) => void;
  /** Set per-annotation font size override (audit #12); null clears it. */
  setMeasureFontSize: (imageId: string, measureId: string, size: number | null) => void;
  /** Set (or, with undefined, clear back to "image default") one measure's
   *  display-unit override. A DISPLAY preference — no undo entry, never
   *  touches `pts`/geometry (measure display-units feature). */
  setMeasureDisplayUnit: (
    imageId: string,
    measureId: string,
    unit: DisplayUnit | undefined,
  ) => void;
  /** Apply one display-unit override to every measure on the image
   *  ("apply to all measures on this image"); same no-undo idiom as
   *  setMeasureDisplayUnit. */
  setAllMeasureDisplayUnits: (imageId: string, unit: DisplayUnit | undefined) => void;
  /** marquee multi-selection (shift-drag on the stage) */
  selectedMulti: string[];
  setSelectedMulti: (ids: string[]) => void;
  /** Remove all measures (or only the given kinds), undoably. */
  clearMeasures: (imageId: string, kinds: MeasureKind[] | null) => void;
  setSelectedMeasure: (id: string | null) => void;
  setRoiStats: (measureId: string, stats: RoiStats) => void;
  setCaptureMode: (mode: CaptureMode) => void;
  setSpecnavPixel: (p: [number, number] | null) => void;
  setFourdNavPixel: (p: [number, number] | null) => void;
  setLayersOverlay: (o: LayersOverlayState | null) => void;
  setLayersEdit: (b: boolean) => void;
  setLayersEditReq: (p: number[] | null) => void;
  setLayersFocusReq: (k: number | null) => void;
  setPanTool: (on: boolean) => void;
  setProfileWidth: (w: number) => void;
  setProfileReduce: (r: "mean" | "sum") => void;
  setToolsLayout: (v: "cards" | "unified") => void;
  setOverlay: (patch: Partial<OverlayStyle>) => void;
  setScaleBar: (imageId: string, patch: Partial<ScaleBarState>) => void;
  /** Set or clear (null) the per-image tilt correction (#34). */
  setTilt: (imageId: string, t: TiltSettings | null) => void;
  setStackFrame: (imageId: string, frame: number) => void;
  setFixedZoomDims: (w: number, h: number) => void;
  setTheme: (choice: Theme | "system") => void;
  toggleTheme: () => void;
  setAccent: (accent: Accent) => void;
  setDensity: (density: Density) => void;
  setScaleBarVisible: (on: boolean) => void;
  toggleLeft: () => void;
  toggleRight: () => void;
  toggleMinimap: () => void;
  toggleColorbar: () => void;
  setColorbarSide: (side: ColorbarSide) => void;
  toggleScaleBar: () => void;
  setCmdk: (open: boolean) => void;
  setShorts: (open: boolean) => void;
  setRadial: (at: { x: number; y: number } | null) => void;
  openTool: (kind: ToolKind) => void;
  closeTool: (kind: ToolKind) => void;
  focusTool: (kind: ToolKind) => void;
  moveTool: (kind: ToolKind, x: number, y: number) => void;
  setExportOpen: (open: boolean) => void;
  setBatchOpen: (open: boolean) => void;
  setCalibOpen: (open: boolean) => void;
  setMetaOpen: (open: boolean) => void;
  setPrefsOpen: (open: boolean) => void;
  setGalleryOpen: (open: boolean) => void;
  setFolderOpen: (open: boolean) => void;
  setLaunchContext: (
    ctx: { dir: string | null; files: { name: string; path: string }[] } | null,
  ) => void;
  setStatus: (msg: string) => void;

  // ── ROI Manager (Tier-2 #5) ─────────────────────────────────────────
  /** Save the given measure (must be roi/ellipse kind) under `name` for
   *  the specified image.  Replaces an existing entry with the same name. */
  saveRoi: (imageId: string, name: string, roi: Pick<SavedRoi, "kind" | "pts">) => void;
  /** Re-create a saved ROI as the active measure+selection for an image. */
  recallRoi: (imageId: string, roiId: string) => void;
  /** Remove one named ROI from the list. */
  deleteRoi: (imageId: string, roiId: string) => void;
  /** Bulk-replace the saved-ROI list — used on session load. */
  seedSavedRois: (map: Record<string, SavedRoi[]>) => void;
}
