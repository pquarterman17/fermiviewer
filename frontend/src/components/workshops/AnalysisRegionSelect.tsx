import { useId } from "react";

import type { AnalysisRoi } from "../../hooks/useAnalysisRoi";
import { useRegionPreview } from "../../hooks/useRegionPreview";
import { formatRegionPreview } from "../../lib/regionPreviewFormat";

interface RegionOption {
  value: string;
  label: string;
}

export default function AnalysisRegionSelect({
  choice,
  options,
  disabled,
  onChange,
  imageId = null,
  roi = null,
}: {
  choice: string;
  options: RegionOption[];
  disabled: boolean;
  onChange: (choice: string) => void;
  /** With an image, the row also reports what the choice selects — pixel
   *  count, share of the image, physical area — as the analysis will read
   *  it (POST /api/regions/preview), before anything runs. */
  imageId?: string | null;
  /** The 1-based inclusive box the choice resolves to; null = whole image. */
  roi?: AnalysisRoi | null;
}) {
  const id = useId();
  const { preview, error } = useRegionPreview(imageId, { roi });
  const summary = error
    ? `preview: ${error}`
    : preview
      ? formatRegionPreview(preview)
      : "";
  return (
    <>
      <div className="fvd-ws-row">
        <label className="k" htmlFor={id}>Region</label>
        <select
          id={id}
          value={choice}
          disabled={disabled}
          style={{ flex: 1, minWidth: 0 }}
          title="Limit analysis to a selected or named ROI"
          onChange={(event) => onChange(event.target.value)}
        >
          {options.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
      </div>
      {imageId && summary && (
        <div className="fvd-ws-note" data-testid="region-preview-summary">
          {summary}
        </div>
      )}
    </>
  );
}
