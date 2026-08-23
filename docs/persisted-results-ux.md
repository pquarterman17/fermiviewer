# Persisted results UX contract

**Status:** Implemented by roadmap item 1B

**Format decision:** [ADR 0004](adr/0004-project-results-section.md)

**Roadmap:** `plans/MICROSCOPY_FEATURE_ROADMAP.md`, items 1–2

## Purpose

A saved analysis result is a scientific record, not a notification and not a
second copy of its originating workshop. The first view must answer four
questions without expanding details:

1. What analysis ran, and when?
2. What are the primary values and uncertainties?
3. Which image, region, method, and calibration produced them?
4. Is anything incomplete, degraded, or scientifically questionable?

The representative implementation is the EDS quantification card in **Window
→ Analysis Workspaces → Results & Methods**. The same hierarchy is the visual
contract for later result types.

## Card hierarchy

1. **Identity:** modality mark, human label, analysis type, timestamp, and
   terminal status.
2. **Primary values:** up to six scalar outputs, retaining the output name,
   unit, and optional uncertainty. Missing uncertainty is omitted rather than
   shown as zero.
3. **Method context:** source links, resolved method/beam voltage, region
   snapshot count, and calibration snapshot/source.
4. **Review state:** scientific warnings are prominent and distinct from
   technical degradation. Failed and cancelled records show the recorded
   reason instead of presenting empty values as a successful result.
5. **Products and provenance:** output-kind chips provide an inventory;
   result ID, exact analysis key, app version, and resolved parameters remain
   available under progressive disclosure.

The card never computes or reformats scientific meaning beyond locale-aware
number display. Labels, values, units, uncertainty, warnings, and resolved
parameters come from the persisted record.

## State rules

- `completed`: show values and context normally.
- `completed` with `missing_members`: label the record **Degraded**, keep all
  surviving metadata visible, and state how many payloads could not be read.
- `failed`: show **Analysis failed** and its recorded error; do not imply that
  absent outputs are zero.
- `cancelled`: show **Analysis cancelled** and its reason.
- unavailable source: preserve its saved name/ID and mark the source missing;
  never silently discard the link.
- no results: explain that capture is not yet connected (item 1C), so the
  empty state does not promise that current workshop runs are already saved.

## 1A consumability review

The item-1A schema can construct the item-2 card, filtering, comparison, and
methods surfaces without another manifest revision:

| UX need | Persisted field(s) | Finding |
| --- | --- | --- |
| identity and ordering | `id`, `label`, `analysis`, `created_at`, `app_version` | sufficient |
| source/sample grouping | `source_ids`, `derived_ids` plus project image/sample data | sufficient |
| values and uncertainty | typed `outputs`; scalar `{value, unit, sigma}` | sufficient |
| tables, curves, maps, figures | output `kind`, inline `data`, optional member | sufficient; item 1C needs query/download access to member data |
| methods and rerun inputs | resolved `params` | sufficient if adopters persist defaults after resolution |
| ROI traceability | `region_ids` plus immutable `regions` snapshots | sufficient |
| calibration traceability | extensible calibration snapshots | sufficient |
| review/failure state | `warnings`, `status`, `error`, route-only `missing_members` | sufficient |
| comparison compatibility | `analysis`, output names/kinds/units, params, calibration | sufficient for explicit compatibility rules in item 2B |

The schema gate for item 1C is therefore cleared. No format change is needed.

## Contract for item 1C adopters

The shared creation API should enforce these conventions before workshops
start emitting records:

- persist resolved parameters, including defaults, rather than only the form
  fields the user changed;
- use stable analysis keys such as `eds.quantify`;
- give scalar outputs concise scientific names (for EDS, element symbols),
  canonical units, and `sigma` only when it is defensible;
- keep warning text suitable for a scientific review note, not a transient
  toast or debug log;
- snapshot source calibration and regions at compute time;
- record failed and cancelled attempts without fabricated outputs;
- expose result-member data through the query API so later detail,
  comparison, and export views do not need to parse `.fvp` files in the
  browser.

## Accessibility and responsive behavior

- The card is an article with its heading as the accessible name.
- Status and degradation messages are text, not color-only signals.
- Source links are real buttons and disabled when the source is unavailable.
- Filters expose `aria-pressed`; metrics and output inventories have labels.
- At compact widths the metric grid collapses before text is truncated, and
  the floating workshop remains internally scrollable.
- Dark and light themes use shared application tokens; warning, success, and
  degradation treatments retain a text label in both themes.
