# Elemental Analysis workspace

One workspace serves both EDS and EELS spectrum-image cubes. It opens
automatically the first time a cube becomes active and can be reopened from the
Inspector's **Elemental** tab or the Analysis/Window menus. The Inspector
contains only a launcher: mounting a second full workshop caused duplicate map
and spectrum requests and left two independent sets of controls on screen.

## Why one workspace

EDS and EELS were separate workshop windows, and that is how EDS accumulated
zoom, per-element colours, integration and the Maps workflow while EELS got
none of them — and how the Inspector ended up launching a workspace for EDS
but mounting a whole second workshop inline for EELS.

Sharing a shell makes the divergence structural rather than a matter of
remembering. Maps and Explore are the same components for both modalities;
only Quantify and Model fit swap their internals, because only those are
genuinely different physics (Cliff–Lorimer / ZAF / ζ and a Kramers continuum
on one side, cross-sections and power-law backgrounds on the other).

The modality is a property of the open cube, not of which menu item was used:
`resolveSpectralModality` decides it from metadata → filename → format →
energy range, and the badge in the tab strip shows both the answer and the
reason. Changing it re-routes that dataset and is remembered.

Code follows the same three-way split, because "which tier is this?" is the
question that decides whether a feature can be shared:

| tier | what belongs there | examples |
|---|---|---|
| `lib/spectrum/`, `components/spectrum/` | any spectrum, elements or not | zoom ranges, integration regions, the plot, the zoom bar |
| `lib/elemental/`, `components/elemental/` | element-centric, modality-agnostic | element colours, the periodic table, identification, the element list, montage, overlay, figure export |
| `lib/eds/`, EDS/EELS components | genuinely different physics | EDS background models (linear flanks, Kramers), K/L/M line markers |

Naming everything "elemental" would be the same category error in the other
direction: `zoomRange.ts` is axis arithmetic that would serve a diffraction
profile with no elements in sight.

## Workspace modes

- **Explore** is the fast qualitative path. It owns the sum, pixel, and ROI
  spectrum; characteristic-line navigation; energy-window/background controls;
  and the current element map.
- **Quantify** runs Cliff–Lorimer or ZAF quantification and registers nonblank
  atomic-percent maps in the image library.
- **Maps** is the primary path: identify → confirm → colour-coded maps. It is
  shared by both modalities.
- **Model fit** contains the physical continuum, peak-deconvolution, artifact,
  and recalibration controls. It is intentionally separated from routine
  spectrum/map browsing.

Switching modes does not discard current results.

The generic multi-channel compositor that used to back the Composite tab still
exists as `ChannelComposite`, but only for the colour-overlay tool, which
blends arbitrary same-size library images. Its channels are filenames rather
than elements, so it takes an explicit colour per channel — conflating it with
the elemental overlay is what briefly made the colour-overlay tool resolve
colours from the element registry keyed on truncated image names.

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
the energy window remain available in either display mode.

### Zoom and the energy window

Two gestures share the spectrum, so they are deliberately separated:

| Gesture | Effect |
|---|---|
| Drag | Zoom the energy axis |
| Shift + drag | Set the element-map energy window |
| Wheel | Zoom about the energy under the cursor |
| Double-click | Reset to the full range |

None of those announce themselves, so the zoom bar under the plot carries the
same operations explicitly: numeric view bounds, pan left/right, zoom in/out,
and Reset. **Zoom to window** beside the window spinners frames the current
window with context on both sides, and clicking a pinned integration region
does the same for that region.

The view is state owned by the explorer, not by uPlot: `null` means "show
everything", which is what lets a Reset survive switching to a spectrum with a
different energy range. Switching cubes clears the zoom.

The window drag was previously bound to the `<canvas>` element. uPlot builds
its wrapper as under → canvas → over, with `.u-over` absolutely positioned
across the plot area, so pointer events inside the plot landed on `.u-over` and
bubbled to the wrapper — never reaching the sibling canvas. The window drag
therefore only fired in the axis gutters, where its `offsetX - bbox.left`
arithmetic also mixed CSS pixels with uPlot's device-pixel `bbox`. The gesture
now goes through `u.over` and uPlot's own select machinery, suppressing the
native zoom for exactly the drag that began with shift held.

### Integration readout

Under the spectrum, a live line reports what the current energy window
contains: channel count, gross counts, the background subtracted, net ± 1σ from
counting statistics, and the net as a share of the whole spectrum. It is
computed client-side from the displayed spectrum, so dragging the window costs
no request — and it follows the source, answering "how much signal is in this
window *on this pixel/ROI/whole cube*".

The background models are a port of `calc/eds_maps.py` (`_side_windows`,
`element_map`, `_kramers_bg_map`), so the readout describes the same quantity
the element map integrates; `frontend/src/lib/eds/integrate.test.ts` pins the
TypeScript against values produced by that Python. One difference is intentional: the map
clamps each pixel's net to ≥ 0, while the readout reports a negative net as-is.
A negative net means the window holds no peak above its background, and hiding
that behind a clamp would misreport an empty window as zero signal.

**+ Add region** pins the current integral to a table — element (or the energy
range for an unnamed window), window, background model, net ± 1σ and percent.
A pinned region is a snapshot of the spectrum it was measured on, not a live
view; re-integrating it later against a different spectrum would silently
rewrite a number the user already read. Clicking a region restores its window,
background and element and frames it on the plot. The table exports to CSV,
carrying the source spectrum per row.

### Element-map display

The selected energy window renders as a full-width map rather than a thumbnail.
It uses the application's shared perceptual colormaps and defaults to a robust
1st–99th percentile display window so isolated hot pixels do not flatten the
rest of the signal. Full-range and higher-contrast presets are available. The
colorbar reports the active display limits, while the footer preserves the true
minimum and maximum—including negative background-subtracted values.

The element control starts as a compact list so the map remains near the
spectrum. **Table** expands the full periodic table for elements not declared in
the acquisition metadata; that choice is remembered.

**Add to library** registers the current map as a derived image without taking
the user away from the EDS cube. The chosen colormap is applied to the derived
image, which then appears in the filmstrip for full-stage inspection, comparison,
and export. **+ Composite** remains available for named element windows.

## Element colours

One registry (`lib/eds/elementColors.ts`, persisted to localStorage) decides
what colour an element is drawn in, everywhere in the workspace:

- composite channels
- the single-element map tint and its colorbar
- the spectrum's characteristic-line markers
- the model-fit deconvolved peak curves
- the composition-profile lines
- the swatch beside each pinned integration region

Set it from the swatch under the element picker — a colour input, the eight
palette presets, and **Default** to drop the override — or from a composite
channel's colour input, which writes to the same registry. Resolution order per
symbol is override → curated colour → a golden-angle hue keyed on the element's
position in the periodic table, so even uncurated elements get distinct,
stable colours.

This replaced an index-into-a-palette assignment, under which a channel's
colour depended on the order elements were added: the same element could be red
in a Quantify run and green after an Explore pick, and the composite disagreed
with the spectrum markers. `Channel` therefore stores no colour at all — it is
resolved at blend time.

**Add to library** can carry the element tint onto the derived image. The tint
is generated per element rather than being one of the shared named colormaps,
so it is published through the application's single `custom` colormap slot; the
button's tooltip says so, because that slot is shared with the user's own
custom colormap.

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

Explore map requests use a 120 ms trailing debounce. A newer energy window or
background selection aborts the request it supersedes, retains the current map
while the replacement is loading, and ignores aborted failures. The live stage
probe uses its separate bounded debounce so it continues updating during a drag.

The mounted explorer caches its whole-cube spectrum, so returning from a pixel
or ROI is immediate. Moving the integration window does not refetch a spectrum:
the draggable patch is a view over the counts already held by the plot.

Backend spectrum sums accumulate directly into a float64 output instead of
casting the complete cube first. Pixel and ROI extraction slices the native
array before float64 accumulation. Both changes bound temporary memory to the
output spectrum or selected region rather than the entire multi-gigabyte cube.

No spectrum-image read path materializes a float64 copy of the whole cube.
That holds for element maps under every background model — the Kramers
continuum fit slices its flanking windows rather than casting the cube —
for `pixel_spectrum`, and for the summed rasters that image operations,
scale-bar detection, and diffraction calibration derive from a cube.
`tests/test_eds_maps.py` asserts this directly: numpy reports its data
allocations to tracemalloc, so peak memory is measured against the size a
full float64 copy would need.
