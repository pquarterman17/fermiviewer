import type { ImageMeta } from "../../lib/api";
import type { SpectralModality } from "../../lib/spectralModality";
import ModalDialog from "./ModalDialog";

export default function SpectralModalityPrompt({
  meta,
  onChoose,
  onClose,
}: {
  meta: ImageMeta;
  onChoose: (modality: SpectralModality) => void;
  onClose: () => void;
}) {
  const range =
    meta.energy_first !== null && meta.energy_last !== null
      ? `${meta.energy_first.toPrecision(4)}–${meta.energy_last.toPrecision(4)} ${meta.energy_units}`
      : "uncalibrated";
  return (
    <ModalDialog
      ariaLabel="Choose spectrum workflow"
      className="fvd-export fvd-spectral-dialog"
      onClose={onClose}
      style={{ width: "min(440px, calc(100vw - 32px))" }}
    >
      <div className="fvd-dialog-head">
        <strong>Choose spectrum workflow</strong>
        <button className="fvd-icon-btn" onClick={onClose} aria-label="Close">
          ×
        </button>
      </div>
      <p className="fvd-ws-note">
        FermiViewer could not confidently identify whether{" "}
        <strong>{meta.name}</strong> is EELS or EDS. Its spectral range is{" "}
        {range}.
      </p>
      <div className="fvd-spectral-choice-grid">
        <button className="fvd-btn" onClick={() => onChoose("eels")}>
          <strong>Use EELS</strong>
          <span>Edges, backgrounds, fine structure, and loss analysis</span>
        </button>
        <button className="fvd-btn" onClick={() => onChoose("eds")}>
          <strong>Use EDS</strong>
          <span>X-ray spectra, element maps, composites, and quantification</span>
        </button>
      </div>
      <p className="fvd-ws-note">
        This choice is remembered for this dataset and can be changed from the
        Spectrum workflow card in the Image inspector.
      </p>
    </ModalDialog>
  );
}
