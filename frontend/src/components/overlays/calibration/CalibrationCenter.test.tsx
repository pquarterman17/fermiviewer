import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CalibrationProfile, ImageMeta } from "../../../lib/api";
import { useViewer } from "../../../store/viewer";
import CalibrationCenter from "./CalibrationCenter";

const profile: CalibrationProfile = {
  id: "det-1", schema: 1, name: "Ultim Max", kind: "detector", version: 2,
  created_at: "2026-01-01T00:00:00+00:00", updated_at: "2026-09-01T00:00:00+00:00",
  fields: { solid_angle: { value: 0.7, unit: "sr", sigma: 0.05 }, takeoff_angle: { value: 22, unit: "deg" } },
  text: { model: "Ultim Max 170" },
  validity: { valid_from: "2026-01-01", valid_to: null, beam_energy_kev: [80, 300], magnification: null, camera_length_mm: null, note: "" },
  provenance: { source: "datasheet", date: "2026-01-15", operator: "PQ", note: "Factory geometry" },
};

const image: ImageMeta = {
  id: "im", name: "sample.dm4", kind: "image", shape: [10, 10], dtype: "float32",
  pixel_size: 1, pixel_spacing: [1, 1], pixel_unit: "nm", value_unit: "",
  n_channels: null, energy_first: null, energy_last: null, energy_units: "", stage_tilt_deg: null,
  profiles: {}, meta: {},
};

const listProfilesMock = vi.fn();
const getKindsMock = vi.fn();
const applyProfileMock = vi.fn();
const createProfileMock = vi.fn();
const updateProfileMock = vi.fn();
const historyMock = vi.fn();

vi.mock("../../../lib/api", async (original) => ({
  ...(await original<typeof import("../../../lib/api")>()),
  listProfiles: (...args: unknown[]) => listProfilesMock(...args),
  getProfileKinds: (...args: unknown[]) => getKindsMock(...args),
  applyProfile: (...args: unknown[]) => applyProfileMock(...args),
  createProfile: (...args: unknown[]) => createProfileMock(...args),
  updateProfile: (...args: unknown[]) => updateProfileMock(...args),
  getProfileHistory: (...args: unknown[]) => historyMock(...args),
  deleteProfile: vi.fn(), unapplyProfile: vi.fn(), importLegacyCalibrations: vi.fn(),
}));

const fields = {
  microscope: {}, detector: { solid_angle: "sr", takeoff_angle: "deg" }, camera: {},
  acquisition: { pixel_size_row: "", pixel_size_column: "" },
};

beforeEach(() => {
  vi.restoreAllMocks();
  vi.clearAllMocks();
  vi.spyOn(window, "confirm").mockReturnValue(true);
  listProfilesMock.mockResolvedValue([profile]);
  getKindsMock.mockResolvedValue({ kinds: ["microscope", "detector", "camera", "acquisition"], fields });
  historyMock.mockResolvedValue([profile]);
  useViewer.setState({ activeId: "im", images: { im: image }, status: "" });
});

describe("CalibrationCenter", () => {
  it("presents profile values, provenance, and active-image state", async () => {
    render(<CalibrationCenter onClose={vi.fn()} />);
    expect(await screen.findByRole("heading", { name: "Ultim Max" })).toBeVisible();
    expect(screen.getByText("0.7 sr")).toBeVisible();
    expect(screen.getByText("Factory geometry")).toBeVisible();
    expect(screen.getByText("sample.dm4")).toBeVisible();
    expect(screen.getByRole("button", { name: "Apply to image" })).toBeEnabled();
  });

  it("applies a profile and surfaces applicability warnings", async () => {
    applyProfileMock.mockResolvedValue({
      image: { ...image, profiles: { detector: { id: profile.id, name: profile.name, version: 2, applied_at: "now", applicability: ["beam energy outside range"] } } },
      applicability: ["beam energy outside range"],
    });
    render(<CalibrationCenter onClose={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Apply to image" }));
    await waitFor(() => expect(applyProfileMock).toHaveBeenCalledWith("im", "det-1"));
    expect(await screen.findByText("beam energy outside range")).toBeVisible();
    expect(screen.getByRole("button", { name: "Remove profile" })).toBeEnabled();
  });

  it("opens a populated editor and saves a new immutable version", async () => {
    updateProfileMock.mockResolvedValue({ profile: { ...profile, name: "Ultim Max SDD", version: 3 } });
    listProfilesMock.mockResolvedValueOnce([profile]).mockResolvedValueOnce([{ ...profile, name: "Ultim Max SDD", version: 3 }]);
    render(<CalibrationCenter onClose={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    const name = screen.getByLabelText("Name");
    fireEvent.change(name, { target: { value: "Ultim Max SDD" } });
    fireEvent.click(screen.getByRole("button", { name: "Save new version" }));
    await waitFor(() => expect(updateProfileMock).toHaveBeenCalled());
    expect(await screen.findByRole("heading", { name: "Ultim Max SDD" })).toBeVisible();
  });

  it("keeps a half-filled validity pair out of the saved profile", async () => {
    createProfileMock.mockResolvedValue({ profile: { ...profile, id: "new", name: "New detector" } });
    listProfilesMock.mockResolvedValueOnce([profile]).mockResolvedValueOnce([profile]);
    render(<CalibrationCenter onClose={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /New profile/ }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "New detector" } });
    fireEvent.change(screen.getByLabelText("Beam energy minimum"), { target: { value: "80" } });
    fireEvent.click(screen.getByRole("button", { name: "Create profile" }));
    await waitFor(() => expect(createProfileMock).toHaveBeenCalled());
    expect(createProfileMock.mock.calls[0][0].validity.beam_energy_kev).toBeNull();
  });

  it("warns and confirms before replacing an image pixel calibration", async () => {
    const acquisition = {
      ...profile,
      id: "acq-1",
      name: "STEM scan",
      kind: "acquisition" as const,
      fields: {
        pixel_size_row: { value: 2, unit: "nm" },
        pixel_size_column: { value: 2, unit: "nm" },
      },
    };
    listProfilesMock.mockResolvedValue([acquisition]);
    vi.mocked(window.confirm).mockReturnValue(false);
    render(<CalibrationCenter onClose={vi.fn()} />);
    expect(await screen.findByText(/Will set pixel size to 2 nm\/px, replacing 1 nm\/px/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Apply to image" }));
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("replace the image pixel size"));
    expect(applyProfileMock).not.toHaveBeenCalled();
  });

  it("keeps acquisition pixel size atomic and constrains it to length units", async () => {
    createProfileMock.mockResolvedValue({ profile: { ...profile, id: "new", name: "Scan", kind: "acquisition" } });
    listProfilesMock.mockResolvedValueOnce([profile]).mockResolvedValueOnce([profile]);
    render(<CalibrationCenter onClose={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Acquisition" }));
    fireEvent.click(screen.getByRole("button", { name: /New profile/ }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Scan" } });
    fireEvent.change(screen.getByLabelText("Pixel size row"), { target: { value: "2" } });
    const unit = screen.getByLabelText("pixel_size_row unit");
    expect(Array.from(unit.querySelectorAll("option"), (option) => option.value)).toEqual([
      "pm", "Å", "nm", "µm", "mm",
    ]);
    fireEvent.click(screen.getByRole("button", { name: "Create profile" }));
    await waitFor(() => expect(createProfileMock).toHaveBeenCalled());
    expect(createProfileMock.mock.calls[0][0].fields).not.toHaveProperty("pixel_size_row");
    expect(createProfileMock.mock.calls[0][0].fields).not.toHaveProperty("pixel_size_column");
  });

  it("duplicates values but resets provenance and legacy import identity", async () => {
    const legacy = {
      ...profile,
      text: { ...profile.text, legacy_key: "Tecnai|100000" },
    };
    listProfilesMock.mockResolvedValueOnce([legacy]).mockResolvedValueOnce([legacy]);
    createProfileMock.mockResolvedValue({ profile: { ...legacy, id: "copy", name: "Ultim Max copy" } });
    render(<CalibrationCenter onClose={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    expect(screen.getByLabelText("legacy key")).toHaveAttribute("readonly");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(await screen.findByRole("button", { name: "Duplicate" }));
    fireEvent.click(screen.getByRole("button", { name: "Create profile" }));
    await waitFor(() => expect(createProfileMock).toHaveBeenCalled());
    expect(createProfileMock.mock.calls[0][0]).toMatchObject({
      text: { model: "Ultim Max 170" },
      provenance: { source: "manual", date: null, operator: "", note: "" },
    });
    expect(createProfileMock.mock.calls[0][0].text).not.toHaveProperty("legacy_key");
  });
});
