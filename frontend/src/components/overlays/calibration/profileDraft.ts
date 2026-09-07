import type {
  CalibrationProfile,
  ImageMeta,
  ProfileDraft,
  ProfileKind,
  ProfileQuantity,
} from "../../../lib/api";
import {
  canonicalCalibrationUnit,
  convertCalibrationValue,
  formatExtent,
} from "../../Inspector/calibrationUi";

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

export function draftForDuplicate(profile: CalibrationProfile): ProfileDraft {
  const draft = draftFromProfile(profile);
  const { legacy_key: _legacyKey, ...text } = draft.text;
  return {
    ...draft,
    name: `${profile.name} copy`,
    text,
    provenance: { ...emptyProvenance },
  };
}

export interface SpatialCalibrationImpact {
  target: string;
  current: string | null;
  changes: boolean;
}

function spacingLabel(spacing: [number, number], unit: string): string {
  const [row, column] = spacing.map(formatExtent);
  return row === column
    ? `${row} ${unit}/px`
    : `rows ${row} · columns ${column} ${unit}/px`;
}

export function spatialCalibrationImpact(
  profile: CalibrationProfile,
  image: ImageMeta | null,
): SpatialCalibrationImpact | null {
  const row = profile.fields.pixel_size_row;
  const column = profile.fields.pixel_size_column;
  if (!row || !column || row.unit !== column.unit) return null;
  const spacing: [number, number] = [row.value, column.value];
  const currentSpacing = image?.pixel_spacing ?? null;
  const current = currentSpacing && image
    ? spacingLabel(currentSpacing, image.pixel_unit)
    : null;
  let changes = currentSpacing == null || image == null;
  const from = canonicalCalibrationUnit(row.unit);
  const to = canonicalCalibrationUnit(image?.pixel_unit ?? "");
  if (currentSpacing && from && to) {
    const converted = spacing.map((value) => convertCalibrationValue(value, from, to));
    changes = converted.some((value, index) =>
      Math.abs(value - currentSpacing[index]) > Math.max(1e-12, Math.abs(currentSpacing[index]) * 1e-9),
    );
  } else if (currentSpacing && image) {
    changes = row.unit !== image.pixel_unit || spacing.some((value, index) => value !== currentSpacing[index]);
  }
  return { target: spacingLabel(spacing, row.unit), current, changes };
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
