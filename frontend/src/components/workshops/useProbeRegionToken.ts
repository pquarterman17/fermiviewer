import { useRef } from "react";

import type { Rect1 } from "./RegionPicker";

/**
 * One-shot marker for the region the live stage probe just published.
 *
 * The probe loads its own spectrum and then calls setRegion, which would make
 * the workshop's region-load effect fetch the very same data again. Marking
 * the region lets that effect skip exactly one load.
 *
 * The token MUST be consumed when it matches. A marker left set makes every
 * LATER arrival at the same coordinates skip its reload too — the workshop
 * then keeps stale spectrum/fit/quant on screen under a correct-looking region
 * label, which reads as real data rather than as a missing refresh.
 */
export interface ProbeRegionToken {
  /** Record the region the probe published. */
  mark: (rect: Rect1) => void;
  /** Forget any pending marker (image switch — it no longer refers to this image). */
  clear: () => void;
  /** True at most once per mark, for that exact region. */
  consumeIfMatches: (region: Rect1 | null) => boolean;
}

export function useProbeRegionToken(): ProbeRegionToken {
  const token = useRef<string | null>(null);
  const current = useRef<ProbeRegionToken | null>(null);

  // Stable identity so callers may safely read it from inside an effect.
  current.current ??= {
    mark: (rect) => {
      token.current = rect.join(",");
    },
    clear: () => {
      token.current = null;
    },
    consumeIfMatches: (region) => {
      if (!region || token.current !== region.join(",")) return false;
      token.current = null;
      return true;
    },
  };

  return current.current;
}
