// Ask the server how much a region selects BEFORE an analysis runs over it
// (POST /api/regions/preview — roadmap item 4's last box). The summary is
// computed by the same resolver the analysis will use, so it previews the
// actual scope rather than the drawn outline; `includeMask` also fetches
// that raster as a PNG for the stage overlay.

import { useEffect, useState } from "react";

import { previewRegion, type RegionPreviewResponse } from "../lib/api/regions";
import type { AnalysisRoi } from "./useAnalysisRoi";

export interface RegionPreviewScope {
  /** `"set_id/region_id"` (or `"set_id"`): a named workspace region. */
  regionRef?: string | null;
  /** A 1-based inclusive box from a workshop's region select. */
  roi?: AnalysisRoi | null;
}

/** The wire spelling of a box — the frozen `"r1,c1,r2,c2"` string; empty
 *  for "no box", which with no `regionRef` previews the whole image. */
export function roiToString(roi: AnalysisRoi | null | undefined): string {
  return roi ? roi.join(",") : "";
}

export interface RegionPreviewState {
  preview: RegionPreviewResponse | null;
  error: string | null;
  loading: boolean;
}

const IDLE: RegionPreviewState = { preview: null, error: null, loading: false };

export function useRegionPreview(
  imageId: string | null | undefined,
  scope: RegionPreviewScope,
  includeMask = false,
): RegionPreviewState {
  const regionRef = scope.regionRef ?? "";
  const roi = roiToString(scope.roi);
  const [state, setState] = useState<RegionPreviewState>(IDLE);

  useEffect(() => {
    if (!imageId) {
      setState(IDLE);
      return;
    }
    let cancelled = false;
    setState((prev) => ({ ...prev, loading: true, error: null }));
    previewRegion({
      image_id: imageId,
      region_ref: regionRef,
      roi,
      include_mask: includeMask,
    })
      .then((preview) => {
        if (!cancelled) setState({ preview, error: null, loading: false });
      })
      .catch((e: Error) => {
        if (!cancelled) setState({ preview: null, error: e.message, loading: false });
      });
    return () => {
      cancelled = true;
    };
  }, [imageId, regionRef, roi, includeMask]);

  return state;
}
