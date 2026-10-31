// Scan distortion correction commands for the Image menu: scan-line jitter
// within the active image, and drift across the selected images. Both ask
// for their settings, register the corrected result and select it.

import { analyzeFrameDrift, analyzeLineJitter } from "./api";
import { askParams } from "../store/params";
import { useViewer } from "../store/viewer";

export async function correctLineJitter(): Promise<void> {
  const s = useViewer.getState();
  const id = s.activeId;
  if (!id) return;
  const v = await askParams(
    "Correct Scan-Line Jitter",
    [
      {
        key: "max_shift",
        label: "Largest row offset (px)",
        type: "number",
        default: 5,
        min: 1,
        max: 64,
        hint: "Keep below half the spacing of any strong horizontal lattice.",
      },
      {
        key: "trend_rows",
        label: "Keep trends over (rows)",
        type: "number",
        default: 20,
        min: 0,
        max: 1000,
        hint: "Slower row shifts are kept as real structure (tilt, shear). 0 keeps none.",
      },
    ],
    "Correct",
  );
  if (!v) return;
  s.setStatus("measuring scan-line jitter…");
  try {
    const r = await analyzeLineJitter(id, {
      max_shift: Number(v.max_shift),
      trend_rows: Number(v.trend_rows),
    });
    const now = useViewer.getState();
    now.ingestDerived([r.image]);
    now.setStatus(
      `scan-line jitter corrected: rms ${r.rms.toFixed(2)} px, ` +
        `max ${r.max_abs.toFixed(2)} px → ${r.image.name}`,
    );
  } catch (e) {
    useViewer.getState().setStatus(`jitter: ${(e as Error).message}`);
  }
}

export async function correctFrameDrift(ids: string[]): Promise<void> {
  if (ids.length < 2) return;
  const v = await askParams(
    `Correct Frame Drift (${ids.length} images)`,
    [
      {
        key: "reference",
        label: "Register to",
        type: "select",
        default: "mean",
        options: ["mean", "first"],
        hint: "mean: re-register to the average of a first alignment (best for noisy frames).",
      },
      {
        key: "crop",
        label: "Crop to the area every frame covers",
        type: "boolean",
        default: true,
      },
      {
        key: "keep_frames",
        label: "Also keep each aligned frame",
        type: "boolean",
        default: false,
      },
    ],
    "Correct",
  );
  if (!v) return;
  const s = useViewer.getState();
  s.setStatus(`correcting drift across ${ids.length} images…`);
  try {
    const r = await analyzeFrameDrift(ids, {
      reference: v.reference === "first" ? "first" : "mean",
      crop: Boolean(v.crop),
      keep_frames: Boolean(v.keep_frames),
    });
    const now = useViewer.getState();
    now.ingestDerived([...r.frames, r.average]);
    now.setStatus(
      `drift corrected across ${ids.length} images: max ${r.max_abs.toFixed(1)} px → ` +
        r.average.name,
    );
  } catch (e) {
    useViewer.getState().setStatus(`drift: ${(e as Error).message}`);
  }
}
