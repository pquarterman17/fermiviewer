import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ImageMeta } from "./api";
import { analyzeFrameDrift, analyzeLineJitter } from "./api";
import { askParams } from "../store/params";
import { useViewer } from "../store/viewer";
import { correctFrameDrift, correctLineJitter } from "./scanCorrection";

vi.mock("./api", async (importActual) => ({
  ...(await importActual<typeof import("./api")>()),
  analyzeLineJitter: vi.fn(),
  analyzeFrameDrift: vi.fn(),
}));
vi.mock("../store/params", () => ({ askParams: vi.fn() }));

const meta = (id: string, name = `${id}.dm4`): ImageMeta => ({
  id,
  name,
  kind: "image",
  shape: [8, 8],
  dtype: "float32",
  pixel_size: null,
  pixel_unit: "px",
  value_unit: "",
  n_channels: null,
  energy_first: null,
  energy_last: null,
  energy_units: "",
  stage_tilt_deg: null,
  meta: {},
});

beforeEach(() => {
  vi.mocked(askParams).mockReset();
  vi.mocked(analyzeLineJitter).mockReset();
  vi.mocked(analyzeFrameDrift).mockReset();
  useViewer.setState({ order: [], images: {}, activeId: null, selected: [] });
  useViewer.getState().ingest([meta("a"), meta("b")]);
  useViewer.getState().setActive("a");
});

describe("correctLineJitter", () => {
  it("sends the chosen settings and selects the corrected image", async () => {
    vi.mocked(askParams).mockResolvedValue({ max_shift: 4, trend_rows: 30 });
    vi.mocked(analyzeLineJitter).mockResolvedValue({
      image: meta("j", "dejitter(a.dm4)"),
      offsets: [0, 0.5],
      rms: 0.42,
      max_abs: 1.3,
    });
    await correctLineJitter();
    expect(analyzeLineJitter).toHaveBeenCalledWith("a", { max_shift: 4, trend_rows: 30 });
    const s = useViewer.getState();
    expect(s.activeId).toBe("j");
    expect(s.status).toBe("scan-line jitter corrected: rms 0.42 px, max 1.30 px → dejitter(a.dm4)");
  });

  it("does nothing when the dialog is cancelled", async () => {
    vi.mocked(askParams).mockResolvedValue(null);
    await correctLineJitter();
    expect(analyzeLineJitter).not.toHaveBeenCalled();
  });

  it("reports a failure in the status line", async () => {
    vi.mocked(askParams).mockResolvedValue({ max_shift: 5, trend_rows: 20 });
    vi.mocked(analyzeLineJitter).mockRejectedValue(new Error("needs a 2-D greyscale image"));
    await correctLineJitter();
    expect(useViewer.getState().status).toBe("jitter: needs a 2-D greyscale image");
  });
});

describe("correctFrameDrift", () => {
  it("sends the chosen settings and ingests the frames and the average", async () => {
    vi.mocked(askParams).mockResolvedValue({ reference: "first", crop: false, keep_frames: true });
    vi.mocked(analyzeFrameDrift).mockResolvedValue({
      average: meta("avg", "drift-corrected average(2)"),
      frames: [meta("fa"), meta("fb")],
      shifts: [
        [0, 0],
        [1.5, -2],
      ],
      max_abs: 2,
      crop: [0, 8, 0, 8],
    });
    await correctFrameDrift(["a", "b"]);
    expect(analyzeFrameDrift).toHaveBeenCalledWith(["a", "b"], {
      reference: "first",
      crop: false,
      keep_frames: true,
    });
    const s = useViewer.getState();
    expect(s.order).toEqual(expect.arrayContaining(["fa", "fb", "avg"]));
    expect(s.activeId).toBe("avg");
    expect(s.status).toBe(
      "drift corrected across 2 images: max 2.0 px → drift-corrected average(2)",
    );
  });

  it("needs at least two images", async () => {
    await correctFrameDrift(["a"]);
    expect(askParams).not.toHaveBeenCalled();
  });
});
