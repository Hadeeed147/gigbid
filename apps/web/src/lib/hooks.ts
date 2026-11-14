import { useCallback, useEffect, useRef, useState } from "react";
import { getToken } from "./api/client";

/** Load data with explicit loading / error states; `reload` re-fetches. */
export function useLoad<T>(fn: () => Promise<{ data?: T; error?: unknown }>, deps: unknown[] = []) {
  const [data, setData] = useState<T | undefined>();
  const [error, setError] = useState<unknown>();
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fnRef.current();
      setData(r.data);
      setError(r.error);
    } catch (e) {
      setError({ detail: "Cannot reach the GigBid API. Check your connection and try again." });
      void e;
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { data, error, loading, reload, setData };
}

/** Re-run `fn` every `ms` while `active`. */
export function useInterval(fn: () => void, ms: number, active = true) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => ref.current(), ms);
    return () => clearInterval(id);
  }, [ms, active]);
}

export type RunEvent = {
  event: string;
  node?: string;
  status?: string | null;
  summary?: string;
  latency_s?: number | null;
  tokens?: number;
  run_id?: string;
  trace_url?: string | null;
  error?: string | null;
  message?: string;
  graph_status?: string | null;
  ts?: number;
};

/** Live node-by-node events for one graph thread over Server-Sent Events.
 *  The server replays history first, so a refresh never shows an empty timeline. */
export function useRunStream(threadId: string | undefined) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    if (!threadId) return;
    setEvents([]);
    const base = import.meta.env.VITE_API_URL ?? "";
    const es = new EventSource(
      `${base}/api/runs/stream/${encodeURIComponent(threadId)}?token=${encodeURIComponent(getToken() ?? "")}`,
    );
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.onmessage = (m) => {
      try {
        const ev = JSON.parse(m.data) as RunEvent;
        setEvents((prev) => [...prev, ev]);
      } catch {
        /* ignore keep-alives */
      }
    };
    return () => es.close();
  }, [threadId]);
  return { events, connected };
}
