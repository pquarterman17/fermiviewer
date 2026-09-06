import type {
  CalibrationProfile,
  ProfileDraft,
  ProfileKind,
  ProfileQuantity,
} from "../../../lib/api";

export const PROFILE_KINDS: ProfileKind[] = [
  "microscope",
  "detector",
  "camera",
  "acquisition",
];

export const KIND_LABEL: Record<ProfileKind, string> = {
  microscope: "Microscopes",
  detector: "Detectors",
  camera: "Cameras",
  acquisition: "Acquisitions",
};

export const TEXT_FIELDS: Record<ProfileKind, string[]> = {
  microscope: ["make", "model", "serial"],
  detector: ["make", "model", "serial", "detector_type", "window_material"],
  camera: ["make", "model", "serial"],
  acquisition: ["instrument", "mode"],
};

const emptyValidity: ProfileDraft["validity"] = {
  valid_from: null,
  valid_to: null,
  beam_energy_kev: null,
  magnification: null,
  camera_length_mm: null,
  note: "",
};

const emptyProvenance: ProfileDraft["provenance"] = {
  source: "manual",
  date: null,
  operator: "",
  note: "",
};

export function emptyProfile(kind: ProfileKind = "detector"): ProfileDraft {
  return {
    name: "",
    kind,
    fields: {},
    text: {},
    validity: { ...emptyValidity },
    provenance: { ...emptyProvenance },
  };
}

export function draftFromProfile(profile: CalibrationProfile): ProfileDraft {
  return {
    name: profile.name,
    kind: profile.kind,
    fields: Object.fromEntries(
      Object.entries(profile.fields).map(([key, value]) => [key, { ...value }]),
    ),
    text: { ...profile.text },
    validity: { ...profile.validity },
    provenance: { ...profile.provenance },
  };
}

export function withQuantity(
  draft: ProfileDraft,
  name: string,
  value: string,
  unit: string,
  sigma: string,
): ProfileDraft {
  const fields = { ...draft.fields };
  if (value.trim() === "") {
    delete fields[name];
  } else {
    const quantity: ProfileQuantity = { value: Number(value), unit };
    if (sigma.trim() !== "") quantity.sigma = Number(sigma);
    fields[name] = quantity;
  }
  return { ...draft, fields };
}

export function profileSearchText(profile: CalibrationProfile): string {
  return [
    profile.name,
    profile.kind,
    profile.provenance.source,
    profile.provenance.operator,
    ...Object.values(profile.text),
    ...Object.keys(profile.fields),
  ]
    .join(" ")
    .toLowerCase();
}

export function compactDate(value: string): string {
  return value ? value.slice(0, 10) : "Not dated";
}
