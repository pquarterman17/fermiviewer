// Grain segmentation methods offered by the Grains mode, split out of
// GrainsMode.tsx to keep that component under the module size ceiling.

import type { GrainMethod } from "../../../lib/api";

/** A stored result's method can carry an edit suffix ("gradient+merge" from
 *  /grains/edit) or come from an older build — map it back to a method
 *  this panel knows, so the knob/when lookups below can't come back empty. */
export function baseGrainMethod(m: unknown): GrainMethod {
  const base = String(m ?? "").split("+")[0];
  return GRAIN_METHODS.some((g) => g.value === base) ? (base as GrainMethod) : "gradient";
}

// method → the one tuning knob it exposes; higher coarseness / merge / K
// is fewer, larger grains. Classic k-means is the ported MATLAB path.
export const GRAIN_METHODS: {
  value: GrainMethod;
  label: string;
  knob: string;
  when: string;
}[] = [
  {
    value: "gradient",
    label: "Gradient — visible boundaries",
    knob: "coarseness",
    when: "Visible grain boundaries in the image. Fast watershed on the gradient.",
  },
  {
    value: "rag",
    label: "Superpixel — diffraction contrast",
    knob: "merge thr",
    when: "Diffraction-contrast grains. Over-segments, then merges similar regions.",
  },
  {
    value: "orientation",
    label: "Orientation — atomic-res",
    knob: "coarseness",
    when: "Atomic-resolution lattices. Segments by local crystal orientation.",
  },
  {
    value: "kmeans",
    label: "Classic k-means",
    knob: "classes",
    when: "Simple intensity classes. The ported MATLAB path.",
  },
  {
    value: "trained",
    label: "Trained — paint examples",
    knob: "",
    when: "Anything the others miss. You teach it by painting a few examples.",
  },
];
