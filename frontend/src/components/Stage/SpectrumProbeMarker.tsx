interface SpectrumProbeMarkerProps {
  position: { x: number; y: number };
  pixel: [number, number];
  /** Stage viewport, used to keep the label inside it. */
  viewport?: { w: number; h: number };
}

// The label sits above-right of the crosshair and the stage clips its
// overflow, so probing near the top or right edge would hide the readout.
// Flip it to the other side when there is not enough room.
const LABEL_H = 19;
const LABEL_W = 92;

export default function SpectrumProbeMarker({
  position,
  pixel,
  viewport,
}: SpectrumProbeMarkerProps) {
  const flipDown = position.y < LABEL_H + 4;
  const flipLeft = viewport ? position.x > viewport.w - LABEL_W : false;
  const cls = [
    "fvd-specnav-label",
    flipDown ? "flip-down" : "",
    flipLeft ? "flip-left" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div
      className="fvd-specnav-mark"
      style={{ left: position.x, top: position.y }}
      aria-hidden="true"
    >
      <span className={cls}>
        r{pixel[0]} · c{pixel[1]}
      </span>
    </div>
  );
}
