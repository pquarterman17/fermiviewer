interface SpectrumProbeMarkerProps {
  position: { x: number; y: number };
  pixel: [number, number];
}

export default function SpectrumProbeMarker({
  position,
  pixel,
}: SpectrumProbeMarkerProps) {
  return (
    <div
      className="fvd-specnav-mark"
      style={{ left: position.x, top: position.y }}
      aria-hidden="true"
    >
      <span className="fvd-specnav-label">
        r{pixel[0]} · c{pixel[1]}
      </span>
    </div>
  );
}
