"""V8 (agentic, required one of V8/V9): corrective RAG loop in LangGraph.

retrieve -> grade each requirement's best evidence -> re-query weak requirements
with an expanded query -> grade again -> mark requirements with no adequate
evidence as "none" so the writer refuses to claim them (and the decision node
can skip jobs the persona should not bid on).
"""
from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from common.config import cfg
from rag.types import Hit
from rag.variants.base import RetrievalQuery, RetrievalResult, expand_query, round_robin
from rag.variants.v4_outcome import V4Outcome


class CState(TypedDict, total=False):
    q: RetrievalQuery
    k: int
    per_req: dict[str, list[Hit]]
    support: dict[str, str]
    requeries: int
    exemplars: list[dict]
    notes: list[str]


class V8Corrective(V4Outcome):
    name = "v8_corrective"

    def __init__(self, store):
        super().__init__(store)
        self.graph = self._build()

    def _grade(self, hits: list[Hit]) -> str:
        if not hits:
            return "none"
        top = hits[0].score
        thr = cfg("rag.corrective.min_relevance", 0.35)
        return "supported" if top >= thr else ("weak" if top >= thr / 2 else "none")

    def _build(self):
        def retrieve(s: CState) -> CState:
            base = V4Outcome.retrieve(self, s["q"], s["k"])
            return {"per_req": base.per_requirement, "exemplars": base.exemplars, "requeries": 0, "notes": []}

        def grade(s: CState) -> CState:
            return {"support": {r: self._grade(h) for r, h in s["per_req"].items()}}

        def requery(s: CState) -> CState:
            per_req = dict(s["per_req"])
            notes = list(s.get("notes", []))
            for r, status in s["support"].items():
                if status == "supported":
                    continue
                expanded = expand_query(r)
                if expanded == r:
                    continue
                hits = [Hit(h.chunk, h.score, r, "corrective") for h in self.reranked(s["q"].tenant, expanded)]
                if hits and (not per_req[r] or hits[0].score > per_req[r][0].score):
                    per_req[r] = hits[: s["k"] * 2]
                    notes.append(f"re-queried '{r[:50]}' with expanded vocabulary")
            return {"per_req": per_req, "requeries": s["requeries"] + 1, "notes": notes}

        def route(s: CState) -> str:
            weak = any(v != "supported" for v in s["support"].values())
            return "requery" if weak and s["requeries"] < cfg("rag.corrective.max_requeries", 1) else "done"

        g = StateGraph(CState)
        g.add_node("retrieve", retrieve)
        g.add_node("grade", grade)
        g.add_node("requery", requery)
        g.add_edge(START, "retrieve")
        g.add_edge("retrieve", "grade")
        g.add_conditional_edges("grade", route, {"requery": "requery", "done": END})
        g.add_edge("requery", "grade")
        # checkpointer=False: never inherit a parent graph's checkpointer (this loop is stateless)
        return g.compile(checkpointer=False)

    def retrieve(self, q: RetrievalQuery, k: int = 10) -> RetrievalResult:
        out = self.graph.invoke({"q": q, "k": k})
        support = out["support"]
        # requirements with no evidence contribute nothing: refuse to claim them
        per_req = {r: (h if support.get(r) != "none" else []) for r, h in out["per_req"].items()}
        return RetrievalResult(hits=round_robin(per_req, k), per_requirement=per_req, support=support,
                               exemplars=out.get("exemplars", []), notes=out.get("notes", []))
