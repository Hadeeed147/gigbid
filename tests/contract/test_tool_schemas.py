"""Schema snapshot test: fails CI when a tool signature changes unintentionally.
Regenerate on purpose with:  UPDATE_SNAPSHOTS=1 uv run pytest tests/contract"""
import json
import os
from pathlib import Path

import pytest

from mcp_servers.marketplace.server import mcp as marketplace
from mcp_servers.portfolio.server import mcp as portfolio
from mcp_servers.testing import session
from mcp_servers.workspace.server import mcp as workspace

SNAP = Path(__file__).parent / "snapshots"


@pytest.mark.parametrize("name,server", [("portfolio", portfolio), ("marketplace", marketplace),
                                         ("workspace", workspace)])
async def test_tool_schema_snapshot(name, server):
    async with session(server) as s:
        tools = sorted((await s.list_tools()).tools, key=lambda t: t.name)
        current = {t.name: {"input": t.inputSchema, "output": t.outputSchema,
                            "annotations": t.annotations.model_dump(exclude_none=True) if t.annotations else None}
                   for t in tools}
    path = SNAP / f"{name}.json"
    if os.environ.get("UPDATE_SNAPSHOTS") == "1" or not path.exists():
        SNAP.mkdir(exist_ok=True)
        path.write_text(json.dumps(current, indent=1, sort_keys=True))
    assert json.loads(path.read_text()) == json.loads(json.dumps(current)), \
        f"{name} tool schemas changed; if intended, run UPDATE_SNAPSHOTS=1"
