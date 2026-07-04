// On-stage capture banner (GUI v2): a glass pill that names the active
// capture tool and the next click/drag step. Driven entirely by the
// CAPTURE_STEPS table; renders nothing for modes without an entry.

import { CAPTURE_STEPS } from "../../lib/captureSteps";
import type { CaptureMode } from "../../store/viewer";

interface CaptureBannerProps {
  mode: CaptureMode;
  pending: { pts: { x: number; y: number }[] } | null;
  onCancel: () => void;
}

export default function CaptureBanner({
  mode,
  pending,
  onCancel,
}: CaptureBannerProps) {
  const entry = CAPTURE_STEPS[mode];
  if (!entry) return null;

  const multi = entry.steps.length > 1;
  // pending.pts always carries a trailing live-cursor point, so its length
  // is the 1-based index of the step currently being captured.
  const i = pending ? pending.pts.length : 1;
  const hint = entry.steps[Math.min(i, entry.steps.length) - 1];

  return (
    <div className="fvd-glass fvd-capture-banner">
      <span className="dot" />
      <span className="label">{entry.label}</span>
      {multi && (
        <span className="step">
          STEP {Math.min(i, entry.steps.length)}/{entry.steps.length}
        </span>
      )}
      <span className="hint">{hint}</span>
      <kbd>esc</kbd>
      <button
        className="fvd-icon-btn"
        title="Cancel capture  Esc"
        onClick={onCancel}
      >
        ✕
      </button>
    </div>
  );
}
