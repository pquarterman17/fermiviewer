// A species: "a thing with an energy window and a colour", for either EDS or
// EELS (SPECTRAL_WORKSPACE_PLAN #1). Lives in the modality-neutral `spectrum`
// tier because both workspaces use it unchanged — only the defaults differ.
//
// A species is what the USER decided: which things to map, over what windows,
// and which are showing. That is deliberately NOT the same object as
// `elemental/identify.ts`'s IdentifiedElement, which is what auto-ID
// MEASURED — net, sigma, significance, confidence, delta-from-tabulated. That
// evidence is recomputed from the spectrum and has no EELS analogue; a user's
// decisions must survive a re-identification that changes every one of those
// numbers. Evidence in, decision out: auto-ID proposes, the species list
// disposes.
//
// NOTE there is deliberately NO `color` field. Colour resolves from
// `elemental/elementColors`, keyed by symbol, so "Carbon is green" holds on
// the montage, the overlay, the legend and the spectrum labels at once. A
// colour carried on the species would be a second source of truth for it, and
// this repo has already paid for that once (a composite kept passing its own
// palette after the shared type dropped the field, and TypeScript said
// nothing). Resolve colour at the point of drawing; never store it here.

/** A half-open energy interval, in this species' modality unit. */
export interface EnergyWindow {
  lo: number;
  hi: number;
}

/**
 * The window set for one species.
 *
 * Both modalities have exactly one signal window. EELS additionally needs an
 * explicit pre-edge background fit region; EDS infers its flanking background
 * from the signal window, so it never carries one. Item 2 generalises
 * integration over this shape — item 1 only fixes the shape itself.
 */
export interface SpeciesWindows {
  signal: EnergyWindow;
  /** EELS only. Auto-placed by `eelsDefaultWindows` (item 16) and always
   *  user-adjustable afterward — see that function for where it goes. */
  background?: EnergyWindow;
}

export type Modality = "eds" | "eels";

export interface Species {
  /** Stable identity, independent of symbol and transition, so renaming or
   *  re-identifying never orphans a row's window edits. */
  id: string;
  symbol: string;
  /** EDS: the shell whose line is integrated — "K" | "L" | "M".
   *  EELS: the edge label — "K", "L2,3", "M4,5". */
  transition: string;
  /**
   * The REFERENCE energy this species is anchored to — the tabulated line
   * (EDS) or edge onset (EELS), in the modality's unit.
   *
   * Deliberately separate from `windows`: the window starts centred on (EDS)
   * or above (EELS) this energy, but the user may drag it elsewhere, after
   * which the window's midpoint is no longer the line. Keeping the anchor is
   * what lets the list label a row "Fe Kα 6.404" regardless of where its
   * window sits, and what makes item 6's "lock the window to the line"
   * possible at all — a window with no remembered anchor cannot be re-snapped
   * to one.
   */
  energy: number;
  /** Fixes both the window shape AND the energy unit: EDS windows are in keV
   *  (what `/eds/element-map(s)` takes), EELS windows in eV (what the edge
   *  table and `/eels/*` use). Mixing the two silently is the failure this
   *  field exists to make impossible. */
  modality: Modality;
  windows: SpeciesWindows;
  visible: boolean;
}

/** The energy unit a species' windows are expressed in. Derived from the
 *  modality rather than stored, so the two can never contradict. */
export function speciesUnit(modality: Modality): "keV" | "eV" {
  return modality === "eds" ? "keV" : "eV";
}

/** Default half-width of an EDS integration window (keV) — the same value
 *  `/eds/element-maps` and `extract_element_maps` default to, so a species
 *  created here and one mapped server-side agree without being told. */
export const EDS_HALF_WINDOW_KEV = 0.085;

/** Default EELS integration width past the onset (eV). ~50 eV is the
 *  conventional starting width for core-loss edge quantification (Egerton):
 *  wide enough to capture the edge, narrow enough to stay clear of the next
 *  one in a crowded spectrum. */
export const EELS_SIGNAL_WIDTH_EV = 50;

/** Pre-edge background-fit window width (eV), and its gap below the onset.
 *  Numerically the SAME values as the backend's EDGE_FIT_WIDTH_EV /
 *  EDGE_FIT_GAP_EV (calc/eels_identify.py) — kept in lockstep so a species
 *  built here and an edge scored by /eels/auto-assign agree on where the
 *  background comes from without being told. */
export const EELS_BG_FIT_WIDTH_EV = 50;
export const EELS_BG_FIT_GAP_EV = 2;

/** EDS default window: the principal line ± half-window. `lineKev` comes from
 *  the backend's own `line_energy` (via `/eds/line-energy`), never a
 *  transcribed table, so it cannot drift from the window the map is cut on. */
export function edsDefaultWindows(
  lineKev: number,
  halfWindowKev: number = EDS_HALF_WINDOW_KEV,
): SpeciesWindows {
  const half = Math.abs(halfWindowKev);
  return { signal: { lo: lineKev - half, hi: lineKev + half } };
}

/**
 * EELS default windows: the signal window runs from the edge onset to
 * `onset + width`; the background window auto-places immediately below it,
 * from `onset - bgGap - bgWidth` to `onset - bgGap` — the same pre-edge
 * window `/eels/auto-assign` fits its power-law background against.
 *
 * Item 16 (resolved 2026-08-11): auto-place, user-adjustable. The prior
 * "leave it unset pending an owner gate" behaviour is retired — guessing was
 * the risk before the gate was answered; now that the answer is "auto-place
 * from the onset, with the same width/gap the backend uses", leaving it
 * unset would just make every fresh species start unusable until the user
 * manually set a window nothing told them to expect.
 */
export function eelsDefaultWindows(
  onsetEv: number,
  widthEv: number = EELS_SIGNAL_WIDTH_EV,
  bgWidthEv: number = EELS_BG_FIT_WIDTH_EV,
  bgGapEv: number = EELS_BG_FIT_GAP_EV,
): SpeciesWindows {
  const width = Math.abs(widthEv);
  const bgWidth = Math.abs(bgWidthEv);
  const bgGap = Math.abs(bgGapEv);
  return {
    signal: { lo: onsetEv, hi: onsetEv + width },
    background: { lo: onsetEv - bgGap - bgWidth, hi: onsetEv - bgGap },
  };
}

/** Normalise a window to lo <= hi. Edge-dragging (item 4) can invert one by
 *  pulling the left edge past the right; every consumer should be able to
 *  assume it never has to sort. */
export function orderWindow(w: EnergyWindow): EnergyWindow {
  return w.lo <= w.hi ? w : { lo: w.hi, hi: w.lo };
}

function newId(): string {
  return crypto.randomUUID();
}

/** Build an EDS species at its principal line. */
export function edsSpecies(
  symbol: string,
  transition: string,
  lineKev: number,
  opts: { halfWindowKev?: number; visible?: boolean } = {},
): Species {
  return {
    id: newId(),
    symbol,
    transition,
    modality: "eds",
    energy: lineKev,
    windows: edsDefaultWindows(lineKev, opts.halfWindowKev),
    visible: opts.visible ?? true,
  };
}

/** Build an EELS species at an edge onset. Pass `windows` to use an exact
 *  measured pair (e.g. from auto-ID evidence) instead of recomputing a
 *  default from `widthEv` — the same escape hatch `edsSpecies`' `halfWindowKev`
 *  gives EDS, so a seeded species' window matches the one its displayed net
 *  counts were actually measured over. */
export function eelsSpecies(
  symbol: string,
  transition: string,
  onsetEv: number,
  opts: { widthEv?: number; visible?: boolean; windows?: SpeciesWindows } = {},
): Species {
  return {
    id: newId(),
    symbol,
    transition,
    modality: "eels",
    energy: onsetEv,
    windows: opts.windows ?? eelsDefaultWindows(onsetEv, opts.widthEv),
    visible: opts.visible ?? true,
  };
}

/**
 * Split an EELS edge label ("Fe-L2,3") into symbol and transition.
 *
 * The edge table keys on the combined label, but a species stores the two
 * apart — the colour registry is keyed on the SYMBOL alone, so "Fe-L2,3" and
 * "Fe-K" must resolve to the same iron colour rather than to two hues from an
 * unrecognised key. This is the same class of bug as colouring channels by a
 * truncated filename.
 */
export function splitEdgeLabel(label: string): {
  symbol: string;
  transition: string;
} {
  const dash = label.indexOf("-");
  if (dash <= 0) return { symbol: label, transition: "" };
  return {
    symbol: label.slice(0, dash),
    transition: label.slice(dash + 1),
  };
}
