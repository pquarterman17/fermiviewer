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
      <div className="fvd-spectrum-probe-readout" aria-live="polite">
        {active && pixel ? (
          <output>Row {pixel[0]} · Col {pixel[1]}</output>
        ) : (
          <span>
            {active
              ? "Click or drag on the main image"
              : "Explore spectra from the main image"}
          </span>
        )}
      </div>
    </div>
  );
}
