import { useCallback, useEffect, useRef } from "react";

export interface RequestLease {
  signal: AbortSignal;
  /** True only while this is the newest request in the current scope. */
  isCurrent: () => boolean;
}

/**
 * Own one abortable request channel.
 *
 * Starting a request invalidates the previous lease. Changing `scope` (most
 * callers use the source image id) aborts the request and makes every callback
 * from the previous scope stale. Unmounting does the same. Consumers must
 * guard success, failure, and finally handlers with `isCurrent()` because an
 * already-resolved promise can still queue callbacks after an abort.
 */
export function useLatestRequest(scope: unknown) {
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);

  const invalidate = useCallback(() => {
    generation.current += 1;
    controller.current?.abort();
    controller.current = null;
  }, []);

  useEffect(() => {
    invalidate();
  }, [scope, invalidate]);

  useEffect(() => invalidate, [invalidate]);

  const begin = useCallback((): RequestLease => {
    invalidate();
    const token = generation.current;
    const next = new AbortController();
    controller.current = next;
    return {
      signal: next.signal,
      isCurrent: () =>
        token === generation.current && !next.signal.aborted,
    };
  }, [invalidate]);

  return { begin, invalidate };
}
