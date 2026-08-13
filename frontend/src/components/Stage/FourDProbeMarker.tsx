// On-stage marker for the 4D-STEM probe pixel (PLAN_4DSTEM #14, the flagged
// v2 of #4: "probe-picking on the MAIN Stage via a specnav-style capture
// mode"). Structurally mirrors SpectrumProbeMarker.tsx — same crosshair-in-
// a-ring visual language for "a probed pixel on the main Stage" — but kept
// as its own component/CSS classes (see 02-stage.css's shared selectors) so
// the spectral and 4D probe features stay independently stylable and
// testable, matching the two features having separate store state
// (specnavPixel vs fourdNavPixel) and separate capture modes.

interface FourDProbeMarkerProps {
  position: { x: number; y: number };
  pixel: [number, number];
  /** Stage viewport, used to keep the label inside it. */
  viewport?: { w: number; h: number };
}

// Same layout constants as SpectrumProbeMarker: the label sits above-right
// of the crosshair and the stage clips its overflow, so probing near the
// top or right edge would hide the readout without this flip.
const LABEL_H = 19;
const LABEL_W = 92;

export default function FourDProbeMarker({
  position,
  pixel,
  viewport,
}: FourDProbeMarkerProps) {
  const flipDown = position.y < LABEL_H + 4;
  const flipLeft = viewport ? position.x > viewport.w - LABEL_W : false;
  const cls = [
    "fvd-fourdnav-label",
    flipDown ? "flip-down" : "",
    flipLeft ? "flip-left" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div
      className="fvd-fourdnav-mark"
      style={{ left: position.x, top: position.y }}
      aria-hidden="true"
    >
      <span className={cls}>
        r{pixel[0]} · c{pixel[1]}
      </span>
    </div>
  );
}
