import SpectrumNavigationControl from "./SpectrumNavigationControl";
import RegionPicker, { type Rect1 } from "./RegionPicker";

export default function EdsSpectrumSourcePicker({
  imageId,
  liveActive,
  livePixel,
  mapReady,
  spectrumReady,
  onRegion,
  onToggleLive,
  onExportMap,
  onExportSpectrum,
}: {
  imageId: string;
  liveActive: boolean;
  livePixel: [number, number] | null;
  mapReady: boolean;
  spectrumReady: boolean;
  onRegion: (rect: Rect1 | null) => void;
  onToggleLive: () => void;
  onExportMap: () => void;
  onExportSpectrum: () => void;
}) {
  return (
    <div id="eds-spectrum-picker" className="fvd-eds-spatial-picker">
      <div className="fvd-ws-row">
        <span className="k">
          Spectrum source preview: click one pixel or drag an ROI
        </span>
      </div>
      <RegionPicker id={imageId} onRegion={onRegion} pixelMode />
      <SpectrumNavigationControl
        active={liveActive}
        pixel={livePixel}
        onToggle={onToggleLive}
      />
      <div className="fvd-ws-row">
        <button
          className="fvd-btn"
          disabled={!mapReady}
          onClick={onExportMap}
          title="Export the current element map as CSV"
        >
          Export map CSV
        </button>
        <button
          className="fvd-btn"
          disabled={!spectrumReady}
          onClick={onExportSpectrum}
          title="Export the displayed spectrum as CSV"
        >
          Export spectrum CSV
        </button>
      </div>
    </div>
  );
}
