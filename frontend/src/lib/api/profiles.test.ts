import { beforeEach, describe, expect, it, vi } from "vitest";

import { applyProfile, createProfile, deleteProfile, getProfileHistory, getProfileKinds, listProfiles, unapplyProfile, updateProfile } from "./profiles";

const ok = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));

beforeEach(() => { vi.stubGlobal("fetch", vi.fn(() => ok({}))); });

describe("calibration profile API", () => {
  it("uses the profile CRUD and application wire shapes", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockImplementationOnce(() => ok({ profiles: [] }))
      .mockImplementationOnce(() => ok({ kinds: [], fields: {} }))
      .mockImplementationOnce(() => ok({ profile: { id: "p" } }))
      .mockImplementationOnce(() => ok({ profile: { id: "p" } }))
      .mockImplementationOnce(() => ok({ versions: [] }))
      .mockImplementationOnce(() => ok({ image: {} }))
      .mockImplementationOnce(() => ok({ image: {}, applicability: [] }))
      .mockImplementationOnce(() => ok({ deleted: "p" }));
    const draft = { name: "Scope", kind: "microscope" as const, fields: {}, text: {}, validity: { valid_from: null, valid_to: null, beam_energy_kev: null, magnification: null, camera_length_mm: null, note: "" }, provenance: { source: "manual", date: null, operator: "", note: "" } };
    await listProfiles(); await getProfileKinds(); await createProfile(draft);
    await updateProfile("p", draft); await getProfileHistory("p");
    await unapplyProfile("im", "microscope"); await applyProfile("im", "p"); await deleteProfile("p");
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/profiles", "/api/profiles/kinds", "/api/profiles", "/api/profiles/p",
      "/api/profiles/p/history", "/api/profiles/unapply", "/api/profiles/apply", "/api/profiles/p",
    ]);
    expect(fetchMock.mock.calls[3][1]).toMatchObject({ method: "PUT" });
    expect(fetchMock.mock.calls[7][1]).toMatchObject({ method: "DELETE" });
  });
});
