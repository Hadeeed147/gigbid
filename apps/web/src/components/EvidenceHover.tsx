import { useMemo } from "react";

export type Evidence = {
  item_id: string;
  type: string;
  title?: string;
  text: string;
  source?: string;
  date?: string;
  outcome?: string | null;
  score?: number;
  requirement?: string | null;
};
export type ClaimCheck = { text: string; status: string; evidence_ids?: string[]; reason?: string };
export type ActiveClaim = { sentence: string; ids: string[]; check?: ClaimCheck } | null;

const CITE = /\s?\[([a-z_]+:[a-z_]+:[^\]\s]+)\]/g;

export function splitClaims(paragraph: string): { text: string; ids: string[] }[] {
  const sentences = paragraph.split(/(?<=[.!?])\s+(?=[A-Z0-9"'(])/);
  return sentences.map((s) => {
    const ids = [...s.matchAll(CITE)].map((m) => m[1]);
    return { text: s.replace(CITE, "").trim(), ids };
  });
}

export function stripCitations(t: string): string {
  return t.replace(CITE, "");
}

function norm(s: string) {
  return stripCitations(s).toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

export function findCheck(sentence: string, checks: ClaimCheck[]): ClaimCheck | undefined {
  const n = norm(sentence);
  return checks.find((c) => {
    const m = norm(c.text);
    return m === n || (m.length > 20 && (n.includes(m.slice(0, 40)) || m.includes(n.slice(0, 40))));
  });
}

/** The letter as the client will read it, with every evidence-backed claim highlighted.
 *  Hover or focus a claim to see the portfolio evidence that proves it. */
export function EvidenceLetter({
  text,
  checks,
  active,
  onActivate,
  onRewrite,
}: {
  text: string;
  checks: ClaimCheck[];
  active: ActiveClaim;
  onActivate: (c: ActiveClaim) => void;
  onRewrite?: (paragraphIndex: number) => void;
}) {
  const paragraphs = useMemo(() => text.split(/\n{2,}/).filter((p) => p.trim()), [text]);
  let n = 0;
  return (
    <div className="letter" data-testid="letter">
      {paragraphs.map((p, pi) => (
        <div className="para" key={pi}>
          <p>
            {splitClaims(p).map((c, ci) => {
              if (!c.ids.length) return <span key={ci}>{c.text} </span>;
              const label = c.ids.map(() => ++n);
              const isActive = active?.sentence === c.text;
              const claim = { sentence: c.text, ids: c.ids, check: findCheck(c.text, checks) };
              return (
                <span key={ci}>
                  <mark
                    className={`claim${isActive ? " active" : ""}`}
                    tabIndex={0}
                    data-evidence={c.ids.join(" ")}
                    aria-describedby="evidence-rail"
                    onMouseEnter={() => onActivate(claim)}
                    onFocus={() => onActivate(claim)}
                    onClick={() => onActivate(claim)}
                  >
                    {c.text}
                    <sup aria-hidden="true">{label.join(",")}</sup>
                  </mark>{" "}
                </span>
              );
            })}
          </p>
          {onRewrite && (
            <div className="para-tools">
              <button className="btn quiet" onClick={() => onRewrite(pi)}>
                Rewrite this paragraph
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

const TYPE_TEXT: Record<string, string> = {
  case_study: "Case study",
  readme: "Repo README",
  code: "Code",
  review: "Client review",
  cv: "CV",
  proposal: "Past proposal",
};

export function EvidenceRail({ active, index }: { active: ActiveClaim; index: Map<string, Evidence> }) {
  return (
    <section className="panel" id="evidence-rail" aria-live="polite">
      <h2>Evidence</h2>
      {!active && (
        <p className="muted small">
          Point at or tab to a highlighted claim to see the portfolio item that proves it.
        </p>
      )}
      {active && (
        <>
          <p className="small">
            {active.check ? (
              <>
                Claim check:{" "}
                <strong className={`strength ${active.check.status === "supported" ? "strong" : "partial"}`}>
                  {active.check.status.replace("_", " ")}
                </strong>
              </>
            ) : (
              <span className="muted">Cited claim</span>
            )}
          </p>
          {active.ids.map((id) => {
            const e = index.get(id);
            return (
              <div className="evidence-card" key={id} data-testid="evidence-card">
                <div className="src">
                  {e ? `${TYPE_TEXT[e.type] ?? e.type}${e.date ? `, ${e.date}` : ""}` : "Portfolio item"} ({id})
                </div>
                {e ? (
                  <div>{e.text.slice(0, 420)}{e.text.length > 420 ? "…" : ""}</div>
                ) : (
                  <div className="muted">This item is no longer in your portfolio. Regenerate the draft to re-check.</div>
                )}
              </div>
            );
          })}
        </>
      )}
    </section>
  );
}
