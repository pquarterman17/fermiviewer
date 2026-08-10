// Constant-physical-scale lock affordance (plan item 10,
// PROJECT_WORKFLOW_PLAN.md). Item 8 already made Stage.tsx HONOR the lock
// (store/browseScale.ts + lib/geometry.ts resolveScaleView / stageScaleLock.ts)
// — this is the piece that was missing: nothing could turn it on. A toggle
// plus a readout of the scale it's holding, in the active image's own
// pixel_unit (never hardcode µm — real corpus files vary: Helios e-beam
// frames are µm, DM files are typically nm).
//
// Self-contained like ZoomChip/Readout in FloatTools.tsx / StageChrome.tsx:
// reads the active image and the live zoom off the stores directly rather
// than threading props through Stage.tsx.

import { physicalScale } from "../../lib/geometry";
import { useBrowseScale } from "../../store/browseScale";
import { useStageInfo } from "../../store/stage";
import { useViewer } from "../../store/viewer";
import Icon from "../icons/Icon";

/** 3 significant figures, no exponential notation — the ranges pixel
 *  calibrations live in (Å through mm) never need more. */
function formatScale(scale: number): string {
  return Number(scale.toPrecision(3)).toString();
}

export default function ScaleLockChip() {
  const activeId = useViewer((s) => s.activeId);
  const pixelSize = useViewer((s) =>
    activeId ? (s.images[activeId]?.pixel_size ?? null) : null,
  );
  const pixelUnit = useViewer((s) =>
    activeId ? (s.images[activeId]?.pixel_unit ?? "px") : "px",
  );
  const zoom = useStageInfo((s) => s.zoom);
  const locked = useBrowseScale((s) => s.locked);
  const lockedScale = useBrowseScale((s) => s.scale);
  const enable = useBrowseScale((s) => s.enable);
  const clear = useBrowseScale((s) => s.clear);

  if (!activeId) return null;

  const calibrated =
    pixelSize != null && Number.isFinite(pixelSize) && pixelSize > 0;
  // The active image's CURRENT physical scale — same convention as
  // lib/geometry.ts physicalScale(view, pixelSize), using the live z off
  // the stage store instead of threading the full View in as a prop. Used
  // both to seed the lock (so enabling it is a no-op on the current frame)
  // and as the unlocked readout.
  const currentScale =
    calibrated && zoom != null && zoom > 0
      ? physicalScale({ z: zoom, px: 0.5, py: 0.5 }, pixelSize)
      : null;
  // While locked, show the value the lock actually holds — identical to
  // currentScale right after enabling, but it's the locked value (not the
  // per-frame one) that should read out while paging a series.
  const displayScale = locked ? lockedScale : currentScale;

  const toggle = () => {
    if (locked) {
      clear();
    } else if (currentScale != null) {
      enable(currentScale);
    }
  };

  return (
    <div
      className="fvd-glass fvd-scale-lock-chip"
      onPointerDown={(e) => e.stopPropagation()}
    >
      <span
        className="fvd-tool-wrap"
        data-tip={calibrated ? undefined : "Constant scale lock"}
        data-tip-detail={
          calibrated
            ? undefined
            : "This image has no calibrated pixel size — the lock needs one to hold a scale across images."
        }
      >
        <button
          className="fvd-icon-btn"
          aria-label="Lock physical scale"
          aria-pressed={locked}
          data-tip={calibrated ? "Lock physical scale" : undefined}
          data-tip-detail={
            calibrated
              ? "Hold a constant on-screen scale while paging through images, instead of each frame fitting to its own size."
              : undefined
          }
          disabled={!calibrated}
          onClick={toggle}
        >
          <Icon name="lock" />
        </button>
      </span>
      <span className="fvd-scale-readout">
        {displayScale != null
          ? `${formatScale(displayScale)} ${pixelUnit}/px`
          : "—"}
      </span>
    </div>
  );
}
