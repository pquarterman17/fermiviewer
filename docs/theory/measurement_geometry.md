# Measurement geometry — tilt correction in SEM/FIB imaging

## Background

When a sample is imaged at a non-zero stage tilt θ, the image is a
projection of a tilted object. Distances measured directly in the image
are foreshortened along the axis perpendicular to the tilt rotation axis.
`measure_distance` (Python) and `imaging.measureDistance` (MATLAB) apply
the inverse scale factor to recover true sample-frame distances.

## Geometry

### Cross-section geometry (FIB lamella, default)

A FIB cross-section is prepared perpendicular to the primary beam. When
imaged at tilt angle θ (the angle between the sample surface and the
horizontal), the depth axis of the cross-section projects onto the image
plane as:

    D_image = D_true · sin(θ)

To recover the true depth dimension:

    D_true = D_image / sin(θ)

If the measurement segment has components (Δx, Δy) in the image (where Y
is the foreshortened axis, i.e. perpendicular to the tilt rotation axis):

    corrected = sqrt( Δx² + (Δy / sin θ)² )      [TiltAxis='Y']
    corrected = sqrt( (Δx / sin θ)² + Δy² )      [TiltAxis='X']

### Surface geometry (tilted plan-view SEM)

A feature of true in-plane length L perpendicular to the tilt axis appears
foreshortened by cos(θ) in a plan-view image:

    L_image = L_true · cos(θ)

Recovery:

    L_true = L_image / cos(θ)

    corrected = sqrt( Δx² + (Δy / cos θ)² )      [TiltAxis='Y']
    corrected = sqrt( (Δx / cos θ)² + Δy² )      [TiltAxis='X']

## Validator

Both functions enforce θ ∈ (−90°, 90°) exclusive. At ±90° the
geometric model is degenerate (sin(90°) = 1 gives no correction; but the
projection plane becomes parallel to the sample surface and image
interpretation breaks down). Values at the boundary are rejected.

## Implementation

`calc/profiles.py: measure_distance()` — verbatim port of
`+imaging/measureDistance.m`.

### Worked example

FIB cross-section at 52°, pure vertical segment of 10 px:

    corrected_px = 10 / sin(52°) ≈ 12.69 px

With pixel size 0.5 nm/px:

    corrected = 12.69 × 0.5 ≈ 6.35 nm

Plan-view at 30°, horizontal segment of 100 px:

    corrected_px = 100 / cos(30°) ≈ 115.47 px

## API

`POST /api/measure/distance-tilted` — accepts image_id, (x1,y1,x2,y2)
in 1-based pixel coordinates, plus tilt_angle_deg, tilt_axis, geometry.
Returns both the raw and corrected distances in pixels and in calibrated
units (null when the image is uncalibrated).

The frontend distance overlay shows the **corrected** value with a `θ`
indicator when correction is active; both columns appear in CSV exports
so the reviewer can audit the raw measurement.

## References

1. Goldstein, J. I. et al. *Scanning Electron Microscopy and X-Ray
   Microanalysis*, 4th ed. Springer, 2018. Chapter 4: Geometric
   distortions in SEM imaging.

2. Giannuzzi, L. A. & Stevie, F. A. (eds.) *Introduction to Focused Ion
   Beams*. Springer, 2005. Chapter 10: Cross-section metrology and
   measurement corrections.
