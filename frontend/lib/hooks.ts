"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { FetchResult } from "./api";

/**
 * Runs `fn` on an interval (default 5s) and clears it on unmount.
 * `enabled=false` pauses without unmounting. Does NOT invoke immediately —
 * pair with an initial fetch (useApi does this for you).
 */
export function usePolling(
  fn: () => void,
  intervalMs = 5000,
  enabled = true
): void {
  const saved = useRef(fn);
  useEffect(() => {
    saved.current = fn;
  }, [fn]);

  useEffect(() => {
    if (!enabled) return;
    const id = setInterval(() => saved.current(), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs, enabled]);
}

export interface ApiState<T> {
  data: T;
  loading: boolean;
  /** true once at least one response (success or fallback) has arrived. */
  loaded: boolean;
  /** non-null when the last fetch failed (backend down / HTTP error). */
  error: string | null;
  refetch: () => void;
}

/**
 * Fetches once on mount (and whenever `deps` change), exposing loading/error.
 * `loader` must be one of the lib/api getters returning FetchResult<T>.
 * On error the typed fallback is kept as `data` so the page can still render
 * an empty state, while `error` lets the page show a "backend down" banner.
 *
 * Pass `pollMs` to also refetch on an interval (live pages).
 */
export function useApi<T>(
  loader: () => Promise<FetchResult<T>>,
  fallback: T,
  deps: ReadonlyArray<unknown> = [],
  pollMs?: number
): ApiState<T> {
  const [data, setData] = useState<T>(fallback);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  // Bumped on every deps change / refetch; stale async results are discarded.
  const reqId = useRef(0);

  // Keep the latest loader without re-subscribing effects.
  const loaderRef = useRef(loader);
  useEffect(() => {
    loaderRef.current = loader;
  });

  // `run` never synchronously sets state in an effect body — it sets the
  // spinner only after yielding to the microtask queue, then awaits the fetch.
  const run = useCallback(async (showSpinner: boolean) => {
    const id = ++reqId.current;
    // Yield first so this isn't a synchronous setState inside an effect.
    await Promise.resolve();
    if (!mounted.current || id !== reqId.current) return;
    if (showSpinner) setLoading(true);
    const res = await loaderRef.current();
    if (!mounted.current || id !== reqId.current) return;
    setData(res.data);
    setError(res.error);
    setLoading(false);
    setLoaded(true);
  }, []);

  /* eslint-disable react-hooks/exhaustive-deps, react-hooks/set-state-in-effect */
  useEffect(() => {
    mounted.current = true;
    // `run` is async and yields before any setState, so this is a fetch
    // subscription to an external system, not a synchronous cascading render.
    // The dep array is the caller-supplied `deps` (intentionally dynamic).
    void run(true);
    return () => {
      mounted.current = false;
    };
  }, deps);
  /* eslint-enable react-hooks/exhaustive-deps, react-hooks/set-state-in-effect */

  usePolling(() => run(false), pollMs ?? 0, Boolean(pollMs));

  const refetch = useCallback(() => run(true), [run]);

  return { data, loading, loaded, error, refetch };
}

/** Live "now" tick (ms) updated every `everyMs` for client-side countdowns. */
export function useNow(everyMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), everyMs);
    return () => clearInterval(id);
  }, [everyMs]);
  return now;
}
