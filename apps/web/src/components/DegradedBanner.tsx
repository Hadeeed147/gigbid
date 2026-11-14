import { useEffect, useState } from "react";
import { api } from "../lib/api/client";
import { useInterval } from "../lib/hooks";

/** Shown whenever the marketplace (GigSim or Upwork) is unreachable, or the API itself is.
 *  The worker keeps the affected jobs queued and resumes them from their last checkpoint. */
export function DegradedBanner() {
  const [state, setState] = useState<{ down: boolean; reason?: string; apiDown?: boolean }>({ down: false });
  const check = async () => {
    try {
      const { data } = await api.GET("/api/health");
      const m = (data?.marketplace ?? {}) as { up?: boolean; reason?: string };
      setState({ down: m.up === false, reason: m.reason });
    } catch {
      setState({ down: true, apiDown: true });
    }
  };
  useEffect(() => {
    void check();
  }, []);
  useInterval(check, 15000);
  if (!state.down) return null;
  return (
    <div className="banner degraded" role="status" data-testid="degraded-banner">
      <strong>{state.apiDown ? "GigBid is unreachable." : "Marketplace unavailable."}</strong>
      <span>
        {state.apiDown
          ? "Check your connection; your pending approvals are saved."
          : "New jobs and submissions are queued and will resume automatically when it is back. Nothing is lost."}
      </span>
    </div>
  );
}
