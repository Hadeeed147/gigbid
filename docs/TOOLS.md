# Tools

Agents never call GigSim, Upwork, a database or a file directly. Every capability is an MCP tool with a schema, an owner and a test. Schemas are frozen in `tests/contract/snapshots/*.json`, and CI fails if one changes unintentionally.

**Auth.** Our three servers accept a bearer token (`MCP_BEARER_TOKEN`) on the Streamable HTTP endpoint, checked by the MCP SDK's `TokenVerifier`. The calling user and tenant travel in `X-GigBid-User` / `X-GigBid-Tenant` headers, which the agent's tool interceptor sets. They are never tool arguments, so a model cannot pick another tenant. Every call carries `X-Trace-Id`, and the marketplace server writes it to the append-only audit log.

| Tool | Server | Read/Write | Annotations | Auth | Who may call it (allowlist) |
|---|---|---|---|---|---|
| `search_evidence(requirement, k, filters)` | portfolio | read | readOnly, idempotent | bearer + tenant header | matcher, writer, verifier, critic, liaison |
| `get_case_study(item_id)` | portfolio | read | readOnly, idempotent | bearer + tenant header | writer |
| `list_skills()` | portfolio | read | readOnly, idempotent | bearer + tenant header | matcher |
| `search_jobs(query, category, posted_after, limit)` | marketplace | read | readOnly, idempotent, openWorld | bearer + user header, rate-limited | scout |
| `get_job(job_id)` | marketplace | read | readOnly, idempotent, openWorld | bearer + user header, rate-limited | scout, risk |
| `get_client_history(client_id)` | marketplace | read | readOnly, idempotent, openWorld | bearer + user header, rate-limited | risk, pricing |
| `get_connects_balance()` | marketplace | read | readOnly, idempotent, openWorld | bearer + user header, rate-limited | pricing, submit |
| `get_policy()` | marketplace | read | readOnly, idempotent, openWorld | bearer + user header, rate-limited | pricing |
| `get_market_stats(category)` | marketplace | read | readOnly, idempotent | bearer | pricing |
| `list_threads()` | marketplace | read | readOnly, idempotent, openWorld | bearer + user header, rate-limited | liaison, pipeline |
| `list_messages(thread_id)` | marketplace | read | readOnly, idempotent, openWorld | bearer + user header, rate-limited | liaison |
| `list_events(after_seq)` | marketplace | read | readOnly, idempotent, openWorld | bearer + user header, rate-limited | pipeline |
| `create_proposal_draft(job_id, cover_letter, bid_amount, idempotency_key, screening_answers, dry_run)` | marketplace | write (draft, no Connects) | idempotent, not destructive | bearer + user header, audit-logged | approval (dry_run only), submit |
| `submit_proposal(proposal_id, idempotency_key, dry_run)` | marketplace | write (**spends Connects**) | destructive, idempotent | bearer + user header, audit-logged, only after `interrupt()` approval | submit |
| `send_message(thread_id, text, idempotency_key, dry_run)` | marketplace | write (irreversible) | destructive, idempotent | bearer + user header, audit-logged, only after approval | send |
| `free_slots(days_ahead, duration_minutes, max_slots)` | workspace | read | readOnly, idempotent | bearer + user header | liaison |
| `create_interview_hold(start, duration_minutes, title, idempotency_key)` | workspace | write (tentative hold) | idempotent | bearer + user header | send |
| `create_email_draft(to_name, subject, body, idempotency_key)` | workspace | write (draft only) | idempotent | bearer + user header | liaison |

**Write discipline.** Every write takes an `idempotency_key`. The marketplace server keeps its own ledger in front of the adapter (`mcp_servers/marketplace/server.py:_idem`), so a retried call never submits twice or spends Connects twice, even through the live Upwork adapter, which has no idempotency of its own. Keys derive from the graph thread id (`agent/nodes/approval.py:_key`), so a crash between approval and submission replays the same key (tested in `tests/integration/test_bid_graph.py::test_approve_submits_exactly_once_even_after_crash`). `dry_run=true` returns exactly what would be sent and what it costs; the approval screen shows that preview.

**Rate limiting.** A per-user sliding window at 50 requests/min sits below GigSim's 60/min (`marketplace.rate_limit_per_minute`). The GigSim adapter retries 429s using the `Retry-After` header and 5xx errors with exponential backoff, then raises `MarketplaceUnavailable`, which the UI shows as degraded mode.

## Third-party servers

| Server | Used for | Trust rationale |
|---|---|---|
| Official Upwork MCP server (`https://mcp.upwork.com/mcp`, OAuth 2.1) | Live mode: job search, proposal drafts, messages | First-party server run by the platform itself. Every write is a draft the user confirms on Upwork, tokens are stored encrypted per user, and it is reached only through our marketplace port (`mcp_servers/marketplace/adapters/upwork_live.py`). |
| Official GitHub MCP server (`github/github-mcp-server`) | Ingesting a user's repos (READMEs and code) into the portfolio | Maintained by GitHub, run with a read-only token scoped to `repo:read`. Ingestion only reads; nothing writes back. |

Tool names on the Upwork server are mapped in `agent/config.yaml` (`marketplace.upwork_tool_map`). After connecting an account, run `uv run python -m mcp_servers.marketplace.adapters.upwork_live --discover <user_id>` to list the live tools and fix the map. **Status:** the live adapter has not been exercised against a real Upwork account yet; see the R&D report, section 9.

## Tests

- In-memory MCP client tests: `mcp_servers/*/tests/` (no network; `mcp.shared.memory`).
- Schema snapshots: `tests/contract/test_tool_schemas.py` (`UPDATE_SNAPSHOTS=1` to accept an intended change).
- MCP Inspector screenshots: `docs/images/inspector-*.png` (run `npx @modelcontextprotocol/inspector` against `http://localhost:8201/mcp`).
