# Trained-grain spatial preview

## Why this change

The trained grain workflow previously reduced its preview to class percentages.
That answered how much of the image was assigned to each class, but not where
the classifier was wrong or uncertain. A plausible percentage could therefore
hide a poor spatial split.

## User-visible behavior

After painting at least two classes, **Preview** now opens the predicted class
map and provides three view buttons:

- **Source** returns to the original image and painted examples.
- **Classes** shows the winning class at every pixel with the label colormap.
- **Confidence** shows the winning-class probability with a perceptual
  colormap.

The panel reports mean confidence and the fraction of analyzed pixels below a
60% confidence threshold. The existing class fractions and boundary-class
markers remain visible. Preview still does not create connected grains or an
editable grain-label map; that only happens after **Train & segment**.

For rectangular ROI analysis, the registered preview images retain the source
shape and calibration. Summary statistics are calculated only over the ROI;
pixels outside it are zero-filled in the display rasters.

Repeated Preview runs remove the previous pair of preview images from the
session before presenting the new pair, avoiding filmstrip buildup.

## Implementation notes

- `calc/grains_trained.py` now preserves the maximum predicted probability in
  `TrainedPreview`; the classifier and feature extraction are unchanged.
- `/api/grains/train-preview` registers class and confidence rasters tagged
  `grain_preview`, `grain_source`, `grain_roi`, and `preview_kind`. It does not
  set `grain_labels`, so merge/split editing cannot mistake a preview for a
  committed result.
- The React result UI lives in `TrainedGrainPreview.tsx`, keeping the legacy
  `StructureWorkshop.tsx` ratchet below its existing cap.

## Review checklist for Claude

- Confirm that preview images have `grain_preview` but never `grain_labels`.
- Confirm that switching Source / Classes / Confidence preserves the trained
  method and painted strokes.
- Confirm that a second Preview removes the old pair and shows the new maps.
- Inspect confidence display inside a saved ROI and confirm outside-ROI pixels
  are not included in the reported percentages.
- Run the full repository quality gate and exercise **Train & segment** after
  previewing to ensure the committed workflow remains unchanged.
