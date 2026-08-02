import { useState } from "react";

import type { BatchRecipeStep } from "../../lib/api";
import { macroLegacyCount, macroOpSteps, setMacroFromRecipe } from "../../lib/macro";

interface MacroBridgeProps {
  /** The dialog's current recipe steps (op + params only). */
  steps: BatchRecipeStep[];
  disabled: boolean;
  /** Loads steps into the dialog's recipe — reuses BatchDialog's own preset
   *  loader, so a macro is resolved against the server schema exactly like
   *  a saved preset would be. Returns an error message, or nothing on success. */
  onLoad: (steps: BatchRecipeStep[]) => string | void;
}

/** Bridges the recorded macro (lib/macro.ts) and the batch recipe editor:
 *  load the macro's op steps into the dialog (from there, the existing
 *  preset controls save/export it), or push the dialog's current steps
 *  into the persisted macro so "Replay Macro" plays them back. Kept out of
 *  BatchDialog.tsx (near its line ceiling) per the size ratchet. */
export default function MacroBridge({ steps, disabled, onLoad }: MacroBridgeProps) {
  const [message, setMessage] = useState("");

  const loadFromMacro = () => {
    const opSteps = macroOpSteps();
    if (!opSteps.length) {
      setMessage("No batchable steps in the recorded macro");
      return;
    }
    const error = onLoad(opSteps);
    const skipped = macroLegacyCount();
    setMessage(
      error ||
        `Loaded ${opSteps.length} step${opSteps.length === 1 ? "" : "s"} from the macro` +
          (skipped ? ` (${skipped} not batchable, skipped)` : ""),
    );
  };

  const saveAsMacro = () => {
    const n = setMacroFromRecipe(steps);
    setMessage(
      `Saved ${n} step${n === 1 ? "" : "s"} as the recorded macro — ` +
        "replay via Image ▸ Batch & Macro ▸ Replay Macro",
    );
  };

  return (
    <div className="fvd-batch-preset-row">
      <button className="fvd-btn" disabled={disabled} onClick={loadFromMacro}>
        Load Recorded Macro
      </button>
      <button
        className="fvd-btn"
        disabled={disabled || steps.length === 0}
        onClick={saveAsMacro}
      >
        Save Steps as Macro
      </button>
      {message && <span className="fvd-ws-note">{message}</span>}
    </div>
  );
}
