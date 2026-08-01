// KNOWN_EDGES table and the EelsTab type, split out of EelsWorkshop.tsx
// (repo-health #33). Moved verbatim.

export type EelsTab = "Explore" | "Quantify" | "Model fit" | "Advanced";

/** Common EELS edge onsets (eV) for the edge-ID overlay. */
export const KNOWN_EDGES: [string, number][] = [
  ["Li-K", 55],
  ["B-K", 188],
  ["C-K", 284],
  ["N-K", 401],
  ["O-K", 532],
  ["F-K", 685],
  ["Na-K", 1072],
  ["Mg-K", 1305],
  ["Al-K", 1560],
  ["Si-K", 1839],
  ["Si-L2,3", 99],
  ["P-L2,3", 132],
  ["S-L2,3", 165],
  ["Ca-L2,3", 346],
  ["Ti-L2,3", 456],
  ["V-L2,3", 513],
  ["Cr-L2,3", 575],
  ["Mn-L2,3", 640],
  ["Fe-L2,3", 708],
  ["Co-L2,3", 779],
  ["Ni-L2,3", 855],
  ["Cu-L2,3", 931],
  ["Zn-L2,3", 1020],
  ["Sr-L2,3", 1940],
  ["La-M4,5", 832],
  ["Ce-M4,5", 883],
  ["Gd-M4,5", 1185],
];
