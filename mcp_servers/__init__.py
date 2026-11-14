"""GigBid MCP servers. `local_identity` lets in-process callers (tests, in-memory
sessions) set (user_id, trace_id) when there is no HTTP request to carry headers."""
import contextvars

local_identity: contextvars.ContextVar[tuple[str, str] | None] = contextvars.ContextVar("local_identity",
                                                                                         default=None)
