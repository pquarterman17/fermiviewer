# Frontend `pixel_size` read audit (ADR 0008, roadmap 5a-C)

**Date:** 2026-09-06
**Scope:** every read of `ImageMeta.pixel_size` / `pixelSize` under
`frontend/src` (grep `pixel_size|pixelSize`, tests excluded).
**Rule (ADR 0008 §1):** `pixel_size` is the COLUMN extent alone. A read
that only prints or gates on it is fine. A read that turns pixels into a
length, area or angle is geometry and must take `pixel_spacing`
(`[row, column]`), falling back to `pixel_size` as square pixels only when
the pair is absent.

ADR 0008 expected zero geometry findings. The audit found that the whole
client-side measurement stack still multiplied by the scalar: the stage
labels, the Inspector rows, the measurement log, the aggregate statistics,
the Regions table and both profile CSVs. Every one of those is fixed here
with an optional trailing `pixel_spacing` argument, and every square-pixel
path is pinned bit-identical to its previous output.

## Geometry reads (changed)

| Site | What it computed | Was | Now |
| --- | --- | --- | --- |
| `lib/geometry.ts` `physDist`, `tiltDist` | length of a pixel displacement | `hypot(dx, dy) × pixel_size` | `hypot(dx·col, dy·row)`; equal extents keep the single product |
| `lib/geometry.ts` `areaPxToPhysical` | px² → physical area | `pixel_size²` | `row × column` (`DataStruct.pixel_area`) |
| `lib/geometry.ts` `physAngle` | angle at a vertex | pixel-grid angle | components scaled by their own extent first (`calc/calibration.physical_angle_rad`) |
| `Stage/measureGlyphs.tsx` `measureLabel` | on-stage distance / polyline / angle / area labels | scalar | `MeasureLabelCtx.pixelSpacing`, fed by `MeasureOverlay` from `Stage` and `SideBySideStage` |
| `Inspector/measurePanelUtils.ts` `distanceValues`, `measureRowValue`, `showLog`, `showStats` | Inspector rows, measurement log, distance stats | scalar | `MetaLike.pixel_spacing` |
| `lib/measureStats.ts` `computeMeasureStats` | Distance / Angle / Area groups | scalar | `MeasureStatsInput.pixelSpacing` (`MeasurePanel` passes `meta.pixel_spacing`) |
| `lib/regionTable.ts` `regionRows` → `RegionsCard`, W4 roll-up | region physical area | `pixel_size²` | `RegionTableImage.pixel_spacing` |
| `lib/profileCsv.ts` `profileToCsv` | `position_px` column | `dist / pixel_size` | when anisotropic: a two-point line maps by response fraction `dist / length × pixel separation` (the backend's `dist` also carries the tilt stretch, so a map rebuilt from spacing alone would overshoot the endpoint); a polyline maps per segment from `endpointsPx` (a scalar quotient cannot recover pixels along a slanted line); px column dropped when the geometry is unknown; `# pixel_spacing:` header line |
| `lib/profileCsv.ts` `boxProfileToCsv` | `y_<unit>` column | `y_pos × pixel_size` | `y_pos × row`; `x_<unit>` stays `× column` |
| `workshops/PixelInspector.tsx` | cursor position in physical units | `cy × pixel_size` | `cy × row extent` |
| `workshops/LayersMultiCompare.tsx` `mapCompatibility` | may two maps share a layer stack? | compared `pixel_size` only | also compares the row extent, so two maps that agree on columns but not rows are refused |

## Display-only or non-spatial reads (unchanged, correct)

Headline, scale bar and status text are column-scale by contract (ADR 0008
gate G2); the scale bar is a horizontal object, so the column extent is
the right one.

* Scale bar and constant-scale browsing: `Stage/ScaleBarOverlay.tsx`,
  `Stage/ScaleLockChip.tsx`, `Stage/stageScaleLock.ts`,
  `Stage/CompareStage.tsx`, `Stage/SideBySideStage.tsx` (lock),
  `Stage/useStagePointers.ts`, `Stage/StageCtxMenu.tsx` (zoom presets),
  `lib/geometry.ts` `physicalScale` / `viewForPhysicalScale` /
  `resolveScaleView`, `lib/elemental/figureExport.ts`,
  `elemental/MapsTab.tsx`, `elemental/EelsMapsTab.tsx`.
* Calibrated-or-not gates and labels: `Shell/StatusBar.tsx`,
  `Inspector/Inspector.tsx`, `Inspector/CalibrationCard.tsx` (5a-B already
  shows both extents), `Inspector/ScaleBarCard.tsx`, `Inspector/calibrationUi.ts`,
  `overlays/ExportDialog.tsx`, `overlays/CalibrationManager.tsx`,
  `lib/export.ts` (`canBar`), `Shell/MenuBar.tsx`, `Shell/menus/imageMenu.ts`,
  `Stage/MeasureCtxMenu.tsx` (Units group gate),
  `workshops/CrossSectionGuide.tsx`.
* Provenance snapshots, not inputs: `lib/crossSectionReport.ts`,
  `lib/api/layers.ts` (backend result fields), `lib/api/core.ts` types.
* Typed detector/camera pixel sizes, not the image calibration:
  `workshops/DiffractionWorkshop.tsx`, `workshops/DiffractionPanels.tsx`,
  `workshops/diffraction/diffractionGeometry.tsx`,
  `lib/api/diffraction-export.ts`, `lib/api/structure.ts`,
  `lib/persistedResultActions.ts`.
* Writers: `lib/api/metadata-export.ts` (`applyCalibration*`).

## Left as is, noted for follow-up

* `Inspector/RegionsCard.tsx` `lengthDisplay` multiplies circle/ellipse fit
  radii and rms by `pixel_size`. The fit itself (`calc/shape_fit`) runs in
  pixel space, so on anisotropic pixels the fitted circle is not a circle
  in the object and no single scale makes its radius a length. Fixing it
  means fitting in physical coordinates on the backend; the display is
  left as the column-scale reading until then.
* The stage renders every image with square screen pixels, so an
  anisotropic image is drawn stretched. Its measurements are now right;
  its picture is not. Separate roadmap item.
* Backend `uniform_pixel_cal` (used by multi-image analyses) compares
  `pixel_size` only, the same gap `mapCompatibility` had.

## Tests

`lib/geometry.test.ts`, `lib/measureStats.test.ts`, `lib/regionTable.test.ts`,
`lib/profileCsv.test.ts`, `workshops/LayersMultiCompare.test.tsx`: each
geometry helper on the 0.5 × 2.0 nm AFM fixture, and each with an equal
pair pinned `toEqual` / `toBe` the scalar result.
