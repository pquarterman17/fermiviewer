import Icon from "../icons/Icon";

interface SpectrumNavigationControlProps {
  active: boolean;
  pixel: [number, number] | null;
  onToggle: () => void;
}

export default function SpectrumNavigationControl({
  active,
  pixel,
  onToggle,
}: SpectrumNavigationControlProps) {
  return (
    <div className={`fvd-spectrum-probe${active ? " active" : ""}`}>
      <button
        type="button"
        className="fvd-spectrum-probe-toggle"
        aria-label={active ? "Stop live stage probe" : "Start live stage probe"}
        aria-pressed={active}
        onClick={onToggle}
      >
        <span className="fvd-spectrum-probe-icon">
          <Icon name="roi" size={15} />
          <span className="fvd-spectrum-probe-dot" />
        </span>
        <span>Live stage probe</span>
      </button>
      {/* The pixel readout re-renders on every pointermove of a probe drag, so
          it must NOT be a live region — a polite one queues an announcement
          per frame and lags long past pointer-up. (<output> is implicitly
          live, hence the plain span.) Only the armed/idle text announces. */}
      <div className="fvd-spectrum-probe-readout">
        {active && pixel ? (
          <span className="fvd-spectrum-probe-pixel">
            Row {pixel[0]} · Col {pixel[1]}
          </span>
        ) : (
          <span aria-live="polite">
            {active
              ? "Click or drag on the main image"
              : "Explore spectra from the main image"}
          </span>
        )}
      </div>
    </div>
  );
}
