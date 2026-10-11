// The EDS element-map background model.
//
// Lives here, rather than on the map-extraction hook that used to declare
// it, because it is no longer a workshops/-only concern: the per-image map
// settings the species store now carries (`edsSettingsByImage`) need the
// type too, and `store/` must not reach into `components/workshops/` to get
// it. `components/workshops/useEdsElementMap.ts` re-exports this for its
// existing importers rather than declaring its own copy.
export type EdsMapBackground = "linear" | "none" | "bremsstrahlung";

/** Why a bremsstrahlung beam energy cannot be used with this window, or
 *  null: the continuum ends at E₀, so the window must lie below it. */
export function e0Error(e0Kev: number, eHi: number): string | null {
  if (!(e0Kev > 0)) return "Enter the beam energy";
  if (!(e0Kev > eHi)) return `E₀ must exceed the window's upper edge (${eHi.toFixed(3)} keV)`;
  return null;
}
