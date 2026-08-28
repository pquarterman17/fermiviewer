import {
  analyzeParticles,
  diffractionIndex,
  edsQuantify,
  listPersistedResults,
  measurePolyline,
  measureProfile,
  type AnalysisRoi,
  type PersistedResultRecord,
} from "./api";
import { useResultWorkflow, type ResultOpenMode } from "../store/resultWorkflow";
import { useViewer } from "../store/viewer";
import { useWorkshop } from "../store/workshop";

const num = (value: unknown, fallback: number): number =>
  typeof value === "number" && Number.isFinite(value) ? value : fallback;
const text = (value: unknown, fallback: string): string =>
  typeof value === "string" ? value : fallback;

export async function refreshPersistedResults(): Promise<void> {
  useViewer.setState({ persistedResults: await listPersistedResults() });
}

export function openPersistedResult(
  result: PersistedResultRecord,
  mode: ResultOpenMode,
): void {
  const sourceId = result.source_ids?.find((id) => id in useViewer.getState().images);
  if (!sourceId) throw new Error("The source image is not available in this project.");
  const viewer = useViewer.getState();
  viewer.setActive(sourceId);
  if (result.analysis === "measure.profile") {
    const meta = viewer.images[sourceId];
    const h = meta.shape[0] ?? 1;
    const w = meta.shape[1] ?? 1;
    const p = result.params ?? {};
    const wirePoints = Array.isArray(p.points)
      ? p.points as number[][]
      : [p.a, p.b].filter(Array.isArray) as number[][];
    if (wirePoints.length < 2) throw new Error("The saved profile geometry is incomplete.");
    viewer.addMeasure(sourceId, {
      kind: Array.isArray(p.points) ? "polyline" : "profile",
      pts: wirePoints.map(([row, col]) => ({ x: (col - 1) / w, y: (row - 1) / h })),
      width: num(p.width, 1),
    });
    useViewer.setState({
      rightCol: false,
      profileWidth: num(p.width, 1),
      profileReduce: text(p.reduce, "mean") as "mean" | "sum",
    });
    return;
  }
  useResultWorkflow.getState().open(result, mode);
  if (result.analysis === "eds.quantify") viewer.openTool("eds");
  else if (result.analysis === "structure.particles") {
    useWorkshop.getState().setStructureMode("Particles");
    viewer.openTool("structure");
  } else if (result.analysis === "diffraction.index") viewer.openTool("diffraction");
  else throw new Error("This result type does not yet have a reopenable workshop.");
}

export async function rerunPersistedResult(result: PersistedResultRecord): Promise<void> {
  const sourceId = result.source_ids?.find((id) => id in useViewer.getState().images);
  if (!sourceId) throw new Error("The source image is not available in this project.");
  const p = result.params ?? {};
  try {
  if (result.analysis === "eds.quantify") {
    const elements = Array.isArray(p.elements) ? p.elements.filter((x): x is string => typeof x === "string") : [];
    const response = await edsQuantify(sourceId, elements, {
      method: text(p.method, "cliff-lorimer") as "cliff-lorimer" | "zaf",
      thicknessNm: num(p.thickness_nm, 100),
      takeOffAngleDeg: num(p.take_off_angle_deg, 20),
      halfWindowKev: num(p.half_window_kev, 0.085),
      record: true,
    });
    useViewer.getState().ingestDerived(response.maps.filter((m) => m !== null));
  } else if (result.analysis === "structure.particles") {
    const response = await analyzeParticles(sourceId, {
      threshold: num(p.threshold, 0),
      polarity: text(p.polarity, "bright") as "bright" | "dark",
      minArea: num(p.min_area, 1),
      watershed: Boolean(p.use_watershed),
      minMarkerDistance: num(p.min_marker_distance, 3),
      classThresholds: typeof p.class_thresholds === "object" && p.class_thresholds !== null
        ? p.class_thresholds as Record<string, number> : undefined,
      record: true,
    });
    useViewer.getState().ingestDerived([response.labels]);
  } else if (result.analysis === "diffraction.index") {
    const spots = Array.isArray(p.spots) ? p.spots as [number, number][] : [];
    await diffractionIndex(sourceId, spots, {
      pixelSizeMm: num(p.pixel_size_mm, 1),
      cameraLengthMm: p.camera_length_mm == null ? undefined : num(p.camera_length_mm, 0),
      accKv: num(p.acc_voltage_kv, 200),
      roi: (p.roi ?? undefined) as AnalysisRoi | undefined,
      record: true,
    });
  } else if (result.analysis === "measure.profile") {
    const width = num(p.width, 1);
    const reduce = text(p.reduce, "mean") as "mean" | "sum";
    if (Array.isArray(p.points)) {
      const points = (p.points as number[][]).map(([row, col]) => ({ x: col - 1, y: row - 1 }));
      await measurePolyline(sourceId, points, width, reduce, true);
    } else {
      const [ar, ac] = p.a as [number, number];
      const [br, bc] = p.b as [number, number];
      const angle = num(p.tilt_angle_deg, 0);
      await measureProfile(sourceId, { x: ac - 1, y: ar - 1 }, { x: bc - 1, y: br - 1 }, width,
        angle === 0 ? null : {
          angle,
          axis: text(p.tilt_axis, "X") as "X" | "Y",
          geometry: text(p.geometry, "surface") as "cross-section" | "surface",
        }, reduce, true);
    }
  } else throw new Error("This result type cannot be rerun yet.");
  } catch (error) {
    // A requested run can fail after the backend has persisted a failed-state
    // record. Refresh that reviewable failure without masking the real error.
    await refreshPersistedResults().catch(() => undefined);
    throw error;
  }
  await refreshPersistedResults();
}
