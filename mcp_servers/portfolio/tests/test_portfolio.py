from mcp_servers.portfolio.server import mcp
from mcp_servers.testing import session


async def test_tools_resources_prompts_listed():
    async with session(mcp) as s:
        tools = {t.name: t for t in (await s.list_tools()).tools}
        assert {"search_evidence", "get_case_study", "list_skills"} <= set(tools)
        assert tools["search_evidence"].annotations.readOnlyHint is True
        assert tools["search_evidence"].outputSchema is not None
        templates = {t.uriTemplate for t in (await s.list_resource_templates()).resourceTemplates}
        assert "portfolio://case/{item_id}" in templates and "portfolio://proposal/{item_id}" in templates
        prompts = {p.name for p in (await s.list_prompts()).prompts}
        assert "answer_screening_question" in prompts


async def test_search_evidence_returns_typed_items():
    async with session(mcp, user="ai_ml") as s:
        r = await s.call_tool("search_evidence", {"requirement": "retrieval-augmented chatbot over documents", "k": 4})
        assert not r.isError
        items = r.structuredContent["items"]
        assert 0 < len(items) <= 4
        assert all(i["item_id"].startswith("ai_ml:") for i in items)
        assert {"type", "source", "date", "outcome"} <= set(items[0])


async def test_get_case_study_and_resource():
    async with session(mcp, user="fullstack") as s:
        r = await s.call_tool("get_case_study", {"item_id": "fullstack:cs:00"})
        assert not r.isError and r.structuredContent["text"]
        res = await s.read_resource("portfolio://case/fullstack:cs:00")
        assert "Client" in res.contents[0].text


async def test_tenant_scoping():
    async with session(mcp, user="data_analyst") as s:
        r = await s.call_tool("get_case_study", {"item_id": "ai_ml:cs:00"})
        assert r.isError  # another tenant's item is invisible
