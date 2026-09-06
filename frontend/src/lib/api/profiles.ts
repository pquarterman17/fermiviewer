import type { ImageMeta } from "./core";
import { json, post } from "./transport";

export type ProfileKind =
  | "microscope"
  | "detector"
  | "camera"
  | "acquisition";

export interface ProfileQuantity {
  value: number;
  unit: string;
  sigma?: number;
}

export interface CalibrationProfile {
  id: string;
  schema: number;
  name: string;
  kind: ProfileKind;
  version: number;
  created_at: string;
  updated_at: string;
  fields: Record<string, ProfileQuantity>;
  text: Record<string, string>;
  validity: {
    valid_from: string | null;
    valid_to: string | null;
    beam_energy_kev: [number, number] | null;
    magnification: [number, number] | null;
    camera_length_mm: [number, number] | null;
    note: string;
  };
  provenance: {
    source: string;
    date: string | null;
    operator: string;
    note: string;
  };
}

export interface ProfileDraft {
  name: string;
  kind: ProfileKind;
  fields: Record<string, ProfileQuantity>;
  text: Record<string, string>;
  validity: CalibrationProfile["validity"];
  provenance: CalibrationProfile["provenance"];
}

export async function listProfiles(kind?: ProfileKind): Promise<CalibrationProfile[]> {
  const query = kind ? `?kind=${encodeURIComponent(kind)}` : "";
  const result = await json<{ profiles: CalibrationProfile[] }>(
    await fetch(`/api/profiles${query}`),
  );
  return result.profiles;
}

export async function getProfileKinds(): Promise<{
  kinds: ProfileKind[];
  fields: Record<ProfileKind, Record<string, string>>;
}> {
  return json(await fetch("/api/profiles/kinds"));
}

export function createProfile(draft: ProfileDraft): Promise<{ profile: CalibrationProfile }> {
  return post("/api/profiles", draft);
}

export async function updateProfile(
  id: string,
  draft: Omit<ProfileDraft, "kind">,
): Promise<{ profile: CalibrationProfile }> {
  return json(
    await fetch(`/api/profiles/${encodeURIComponent(id)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(draft),
    }),
  );
}

export async function deleteProfile(id: string): Promise<{ deleted: string }> {
  return json(
    await fetch(`/api/profiles/${encodeURIComponent(id)}`, { method: "DELETE" }),
  );
}

export async function getProfileHistory(id: string): Promise<CalibrationProfile[]> {
  const result = await json<{ versions: CalibrationProfile[] }>(
    await fetch(`/api/profiles/${encodeURIComponent(id)}/history`),
  );
  return result.versions;
}

export function applyProfile(
  imageId: string,
  profileId: string,
): Promise<{ image: ImageMeta; applicability: string[] }> {
  return post("/api/profiles/apply", { image_id: imageId, profile_id: profileId });
}

export function unapplyProfile(
  imageId: string,
  kind: ProfileKind,
): Promise<{ image: ImageMeta }> {
  return post("/api/profiles/unapply", { image_id: imageId, kind });
}

export function importLegacyCalibrations(): Promise<{
  created: CalibrationProfile[];
  skipped: string[];
}> {
  return post("/api/profiles/import-calibrations", {});
}
