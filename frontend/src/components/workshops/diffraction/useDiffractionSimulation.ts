// Diffraction workshop "Simulate" tab state + logic, extracted verbatim
// from DiffractionWorkshop.tsx (MAIN_PLAN item 1, pin graduation): phase
// list state, custom-phase import/delete (Diffraction #2), and the
// kinematic-simulation call. Bodies are unchanged — only the closures now
// live in a hook instead of the component, and `simPhase` is threaded back
// to the caller since Calibrate reads it as a fallback standard phase.

import {
  type Dispatch,
  type RefObject,
  type SetStateAction,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import {
  analyzeDiffractionSimulate,
  deleteDiffractionPhase,
  importDiffractionPhase,
  listDiffractionPhases,
  type PhaseInfo,
  type SimulateResult,
} from "../../../lib/api";
import { useViewer } from "../../../store/viewer";

export interface DiffractionSimulationState {
  phases: PhaseInfo[];
  simPhase: string;
  setSimPhase: Dispatch<SetStateAction<string>>;
  simZa: string;
  setSimZa: Dispatch<SetStateAction<string>>;
  simResult: SimulateResult | null;
  scatModel: "fe" | "z";
  setScatModel: Dispatch<SetStateAction<"fe" | "z">>;
  cifInputRef: RefObject<HTMLInputElement | null>;
  onCifFile: (file: File) => void;
  deletePhase: () => void;
  simulate: () => void;
}

export function useDiffractionSimulation(
  activeId: string | null,
  setStatus: (msg: string) => void,
  setBusy: Dispatch<SetStateAction<boolean>>,
): DiffractionSimulationState {
  const [phases, setPhases] = useState<PhaseInfo[]>([]);
  const [simPhase, setSimPhase] = useState("");
  const [simZa, setSimZa] = useState("0 0 1");
  const [simResult, setSimResult] = useState<SimulateResult | null>(null);
  const [scatModel, setScatModel] = useState<"fe" | "z">("fe");
  const cifInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    listDiffractionPhases()
      .then((list) => {
        setPhases(list);
        if (list.length > 0) setSimPhase(list[0].name);
      })
      .catch(() => undefined);
  }, []);

  // ── simulate ──────────────────────────────────────────────────────
  const simulate = useCallback(() => {
    if (!simPhase) return;
    const parts = simZa.trim().split(/\s+/).map(Number);
    if (parts.length !== 3 || parts.some(isNaN)) {
      setStatus("Simulate: zone axis must be three integers, e.g. 0 0 1");
      return;
    }
    setBusy(true);
    analyzeDiffractionSimulate(simPhase, parts as [number, number, number], {
      parentImageId: activeId ?? undefined,
      scatteringModel: scatModel,
    })
      .then((r) => {
        setSimResult(r);
        setStatus(
          `sim: ${r.phase} [${r.zone_axis.join(" ")}] · ` +
            `${r.spots.length} spots · λ ${r.lam_angstrom.toFixed(4)} Å`,
        );
        if (r.image) {
          useViewer.getState().ingestDerived([r.image]);
        }
      })
      .catch((e: Error) => setStatus(`simulate: ${e.message}`))
      .finally(() => setBusy(false));
  }, [simPhase, simZa, activeId, scatModel, setStatus, setBusy]);

  // ── custom-phase import / delete (Diffraction #2) ─────────────────
  const onCifFile = useCallback(
    (file: File) => {
      file
        .text()
        .then((text) => importDiffractionPhase(text, ""))
        .then((p) => {
          setStatus(`phase imported: ${p.name} (${p.centering}, ${p.n_sites} sites)`);
          return listDiffractionPhases();
        })
        .then((list) => {
          setPhases(list);
          const last = list.find((p) => p.custom);
          if (last) setSimPhase(last.name);
        })
        .catch((e: Error) => setStatus(`CIF import: ${e.message}`));
    },
    [setStatus],
  );

  const deletePhase = useCallback(() => {
    const p = phases.find((x) => x.name === simPhase);
    if (!p?.custom) return;
    deleteDiffractionPhase(p.name)
      .then(() => listDiffractionPhases())
      .then((list) => {
        setPhases(list);
        setSimPhase(list[0]?.name ?? "");
        setStatus(`phase deleted: ${p.name}`);
      })
      .catch((e: Error) => setStatus(`delete: ${e.message}`));
  }, [phases, simPhase, setStatus]);

  return {
    phases, simPhase, setSimPhase, simZa, setSimZa, simResult,
    scatModel, setScatModel, cifInputRef, onCifFile, deletePhase, simulate,
  };
}
