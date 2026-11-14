"""RAG unit tests that need no API key (embedding models run on CPU)."""
from rag.ingest.chunkers import fixed_chunks, structured_chunks
from rag.ingest.loaders import RawItem, tag_skills
from rag.retriever import get_store, search
from rag.types import Chunk, Hit
from rag.variants.base import expand_query, round_robin, rrf, rule_requirements
from rag.verify import is_claim, split_sentences, verify


def test_tag_skills_from_names_and_imports():
    assert "celery" in tag_skills("We used Celery for jobs")
    assert "pytorch" in tag_skills("import torch\nfrom torch import nn")
    assert "dbt" in tag_skills("dbt models with tests")


def test_structured_chunks_keep_metadata_and_whole_code():
    item = RawItem("t:cs:1", "case_study", "t", "# A\n" + "word " * 300 + "\n## B\n" + "more " * 200,
                   title="A", project_id="t:p1", client_industry="fintech")
    chunks = structured_chunks(item, size=700)
    assert len(chunks) >= 2 and all(c.project_id == "t:p1" and c.tenant == "t" for c in chunks)
    code = RawItem("t:code:r:main.py", "code", "t", "import torch\n" * 200, title="r/main.py")
    assert len(structured_chunks(code)) == 1
    assert len(fixed_chunks(item)) > 2


def test_rrf_and_round_robin():
    c = [Chunk(f"c{i}", f"i{i}", "x", "case_study", "t") for i in range(4)]
    fused = rrf([[Hit(c[0], 1), Hit(c[1], 1)], [Hit(c[1], 1), Hit(c[2], 1)]])
    assert fused[0].chunk.chunk_id == "c1"
    merged = round_robin({"a": [Hit(c[0], 1), Hit(c[1], 1)], "b": [Hit(c[2], 1), Hit(c[3], 1)]}, 3)
    assert [h.item_id for h in merged] == ["i0", "i2", "i1"]


def test_rule_requirements_and_expansion():
    reqs = rule_requirements("Need help:\n- Celery queue\n- React dashboard\n")
    assert reqs == ["Celery queue", "React dashboard"]
    assert "background task queue" in expand_query("Celery queue")


def test_claim_detection():
    s = split_sentences("I built a churn model that cut losses by 20%. Could we talk Monday? I would start with SQL.")
    claims = [x for x in s if is_claim(x)]
    assert claims == ["I built a churn model that cut losses by 20%."]


def test_tenant_isolation():
    r = search("ai_ml", "React dashboard with Stripe", k=5, variant="v2_hybrid")
    assert all(h.chunk.tenant == "ai_ml" for h in r.hits)


def test_verify_removes_unsupported_claim_with_free_grader():
    store = get_store()
    cs = next(i for i in store.items("ai_ml") if i.type == "case_study")
    text = (f"I built the {cs.title.split(' for ')[0].lower()} described in my portfolio. "
            "I have managed a team of 40 astronauts on the Moon for NASA since 1999.")
    rep = verify(text, "ai_ml", [], grader="ce")
    statuses = {c.text[:20]: c.status for c in rep.claims}
    assert any(v == "unsupported" for v in statuses.values())
    assert "astronauts" not in rep.revised_text
