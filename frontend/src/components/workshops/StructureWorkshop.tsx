// Structure workshop (plan #28 tail): first dedicated UI for the five
// structure endpoints — atom columns (overlay + lattice vectors),
// template match (ROI-as-template, match overlay), CTF (fit plot),
// lattice spacing (two clicks on an FFT) and tile stitching.
//
// The per-mode implementations live in ./structure/ (repo-health #33 split);
// this file keeps the shell, the tiny Atoms delegate, and re-exports the
// module's public surface so no external import site changes.

import { useViewer } from "../../store/viewer";
import AtomColumnPanel from "./AtomColumnPanel";
import {
  STRUCTURE_MODES,
  STRUCTURE_MODE_DESCRIPTIONS,
  useWorkshop,
} from "../../store/workshop";
import LatticeMode from "./LatticeMode";
import ParticlesMode from "./ParticlesMode";
import { GrainsMode } from "./structure/GrainsMode";
import { TemplateMode, GpaMode } from "./structure/TemplateGpaModes";
import { CtfMode, StitchMode } from "./structure/CtfStitchModes";

export { TrainedPreviewLegend } from "./TrainedGrainPreview";
export { grainSourceId } from "../../lib/grainWorkflow";
export { GrainsMode } from "./structure/GrainsMode";
export { paintedReadyCount } from "./structure/TrainedGrainControls";

export default function StructureWorkshop() {
  const activeId = useViewer((s) => s.activeId);
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const mode = useWorkshop((s) => s.structureMode);
  const setMode = useWorkshop((s) => s.setStructureMode);

  const isImage = meta?.kind === "image";

  return (
    <div className="fvd-ws">
      <div className="fvd-seg">
        {STRUCTURE_MODES.map((m) => (
          <button
            key={m}
            className={`fvd-seg-btn${mode === m ? " active" : ""}`}
            onClick={() => setMode(m)}
            title={STRUCTURE_MODE_DESCRIPTIONS[m]}
          >
            {m}
          </button>
        ))}
      </div>
      {!isImage && mode !== "Stitch" ? (
        <div className="fvd-ws-empty">Select a 2D image.</div>
      ) : (
        <>
          {mode === "Atoms" && activeId && <AtomsMode id={activeId} />}
          {mode === "Particles" && activeId && <ParticlesMode id={activeId} />}
          {mode === "Grains" && activeId && <GrainsMode id={activeId} />}
          {mode === "Template" && activeId && <TemplateMode id={activeId} />}
          {mode === "GPA" && activeId && <GpaMode id={activeId} />}
          {mode === "CTF" && activeId && <CtfMode id={activeId} />}
          {mode === "Lattice" && activeId && <LatticeMode id={activeId} />}
          {mode === "Stitch" && <StitchMode />}
        </>
      )}
    </div>
  );
}

// ── Atoms — delegated to AtomColumnPanel ────────────────────────────

function AtomsMode({ id }: { id: string }) {
  return <AtomColumnPanel id={id} />;
}
