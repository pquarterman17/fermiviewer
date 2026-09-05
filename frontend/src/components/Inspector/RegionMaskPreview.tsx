// Under the selected region in the Analysis Regions card: how much the
// region selects — counted by the resolver an analysis will use, not by the
// drawn outline — and a toggle that paints that exact raster on the stage.

import { useEffect, useState } from "react";

import { useRegionPreview } from "../../hooks/useRegionPreview";
import type { ProjectRegion } from "../../lib/api";
import { formatRegionPreview } from "../../lib/regionPreviewFormat";
import { useRegionPreviewStore } from "../../store/regionPreview";

export default function RegionMaskPreview({
  imageId,
  setId,
  region,
}: {
  imageId: string;
  setId: string;
  region: ProjectRegion;
}) {
  const regionRef = `${setId}/${region.id}`;
  const [show, setShow] = useState(false);
  const { preview, error, loading } = useRegionPreview(imageId, { regionRef }, show);
  const showMask = useRegionPreviewStore((state) => state.showMask);
  const clearMask = useRegionPreviewStore((state) => state.clearMask);

  useEffect(() => {
    if (show && preview?.mask_png) {
      showMask({
        imageId,
        regionRef,
        rect: preview.rect,
        href: `data:image/png;base64,${preview.mask_png}`,
      });
    } else {
      clearMask(regionRef);
    }
    return () => clearMask(regionRef);
  }, [show, preview, imageId, regionRef, showMask, clearMask]);

  // a plain rectangle's outline IS its mask: nothing to paint that the
  // region overlay is not already showing
  const paintable = preview?.exact_mask ?? false;
  const summary = loading && !preview
    ? "measuring…"
    : error
      ? `preview: ${error}`
      : preview
        ? formatRegionPreview(preview)
        : "";

  return (
    <div className="fvd-region-preview" data-region-ref={regionRef}>
      <div className="fvd-region-preview-summary" aria-live="polite">{summary}</div>
      <label className="fvd-region-preview-toggle">
        <input
          type="checkbox"
          checked={show}
          disabled={!paintable && !show}
          onChange={(event) => setShow(event.target.checked)}
        />
        <span>
          {paintable || show
            ? "Show exact mask on stage"
            : "Rectangle — its outline is the mask"}
        </span>
      </label>
    </div>
  );
}
