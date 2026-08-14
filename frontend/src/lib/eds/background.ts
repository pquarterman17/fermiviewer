// The EDS element-map background model.
//
// Lives here, rather than on the map-extraction hook that used to declare
// it, because it is no longer a workshops/-only concern: the per-image map
// settings the species store now carries (`edsSettingsByImage`) need the
// type too, and `store/` must not reach into `components/workshops/` to get
// it. `components/workshops/useEdsElementMap.ts` re-exports this for its
// existing importers rather than declaring its own copy.
export type EdsMapBackground = "linear" | "none" | "bremsstrahlung";
