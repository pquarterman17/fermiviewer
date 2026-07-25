# EDS spectrum-image workspace

The EDS workspace is the primary interface for spectrum-image cubes. It opens
automatically the first time a cube becomes active and can be reopened from the
Inspector's **EDS** tab or the Analysis/Window menus. The Inspector deliberately
contains only a launcher: mounting a second full workshop caused duplicate map
and spectrum requests and left two independent sets of controls on screen.

## Workspace modes

- **Explore** is the fast qualitative path. It owns the sum, pixel, and ROI
  spectrum; characteristic-line navigation; energy-window/background controls;
  and the current element map.
- **Quantify** runs Cliff–Lorimer or ZAF quantification and registers nonblank
  atomic-percent maps in the image library.
- **Composite** combines maps selected in Explore or produced by Quantify. Each
  channel has independent visibility, color/ramp, and intensity.
- **Model fit** contains the physical continuum, peak-deconvolution, artifact,
  and recalibration controls. It is intentionally separated from routine
  spectrum/map browsing.

The modes share element-map channels and element text within one mounted
`EdsWorkshop`. Switching modes does not discard current results.

### Spectrum sources and display

Explore starts with the complete whole-cube spectrum. The source bar makes the
three acquisition paths explicit:

- **Whole cube** restores the spatially summed spectrum.
- **Live stage pixel** arms the shared stage probe; moving on the main image
  updates the pixel spectrum without hiding the current curve.
- **Preview pixel / ROI** jumps to the spatial preview. Click selects one pixel;
  drag selects an inclusive rectangular ROI.

The source chip always names the displayed spectrum. Manual source requests show
`Loading…` while retaining the previous plot. The plot supports linear counts or
`log10(counts + 1)` and compact/expanded heights; characteristic-line labels and
the draggable integration window remain available in either display mode.

## Window behavior

EDS opens at 680 × 620 px rather than the generic 360 px workshop width. CSS
viewport limits keep it on-screen. All workshop windows have a lower-right
resize grip; the chosen dimensions remain while that window is open. The body
scrolls independently while the EDS mode bar stays visible.

## Element-map request contract

`POST /api/eds/element-map` treats `bg_width` and `e0_kev` as optional numeric
fields. New clients omit an unset field. The backend also accepts JSON `null`
from older built clients and translates it to the calculation layer's existing
NaN sentinel. No non-finite number is emitted in JSON.

The map response always includes an inline `map`, `shape`, energy bounds,
background mode, and `total_counts`. `map_meta` is present only when
`save_derived=true`; that registered image is what the library and composite
engine consume.

## Performance boundary

Explore requests are interactive and must remain cancellable or ordered when
controls change rapidly. Full-cube sum spectra and multi-element map extraction
need special care for multi-gigabyte cubes; avoid converting an entire cube to
float64 merely to accumulate a narrow energy window.
