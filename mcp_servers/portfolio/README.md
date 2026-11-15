# GigBid Portfolio MCP server

A read-only MCP server that gives an AI agent **evidence search over a freelancer's portfolio**: CV, case studies,
repo READMEs and code, client reviews and past proposals with outcomes. Every result has an item id the agent can
cite, so a proposal can point at the exact project that proves a claim.

Built for GigBid (AI-4016, FAST-NUCES); it works on its own with any MCP client.

## Tools

| Tool | What it does |
|---|---|
| `search_evidence` | Find portfolio evidence for one job requirement (hybrid dense + BM25 retrieval, reranked; filters by type, project, date, outcome) |
| `get_case_study` | Full text and metadata of one portfolio item by id |
| `list_skills` | Skills found across the portfolio, with the items that show each one |

Read-only: no tool writes anything. Bearer-token auth is enabled on HTTP when `MCP_BEARER_TOKEN` is set.

## Install and run

Needs Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/Hadeeed147/gigbid && cd gigbid
uv sync --no-dev

# stdio (for Claude Desktop, Cursor, MCP Inspector) on your own portfolio folder
uv run python -m mcp_servers.portfolio.server --transport stdio --portfolio-dir ./my_portfolio

# streamable HTTP on :8201
uv run python -m mcp_servers.portfolio.server --port 8201
```

The portfolio folder layout is `cv.pdf` or `cv.md`, `case_studies/*.md`, `repos/<name>/README.md` (+ code),
`reviews.json` and `proposals.json`. `data/personas/ai_ml/` is a complete synthetic example.

Docker: `docker compose -f infra/docker-compose.yml up mcp-portfolio`

### MCP client config (stdio)

```json
{
  "mcpServers": {
    "gigbid-portfolio": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/gigbid", "python", "-m", "mcp_servers.portfolio.server",
               "--transport", "stdio", "--portfolio-dir", "/path/to/my_portfolio"]
    }
  }
}
```

Inspect it: `npx @modelcontextprotocol/inspector uv run python -m mcp_servers.portfolio.server --transport stdio --portfolio-dir data/personas/ai_ml`

## Models

Embeddings `BAAI/bge-small-en-v1.5` and reranker `ms-marco-MiniLM-L-6-v2`, both open models running on CPU through
fastembed (ONNX), downloaded on first use. No API key is needed.

Tests: `uv run pytest mcp_servers/portfolio -q`
