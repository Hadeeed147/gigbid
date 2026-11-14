"""Local dev runner for the API / worker that works on Windows too.

psycopg's async driver cannot use Windows' default Proactor event loop, so we run
on a SelectorEventLoop. Linux (Docker, CI, the deployment) is unaffected.
Usage:  uv run python -m scripts.serve api [port]   |   uv run python -m scripts.serve worker
"""
from __future__ import annotations

import asyncio
import selectors
import sys


def loop_factory():
    return asyncio.SelectorEventLoop(selectors.SelectSelector()) if sys.platform == "win32" else asyncio.new_event_loop()


def main() -> None:
    what = sys.argv[1] if len(sys.argv) > 1 else "api"
    if what == "api":
        import uvicorn
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 8000
        server = uvicorn.Server(uvicorn.Config("apps.api.main:app", host="0.0.0.0", port=port, loop="none"))
        asyncio.run(server.serve(), loop_factory=loop_factory)
    elif what == "worker":
        from arq.worker import create_worker

        from worker.main import WorkerSettings

        async def run():
            w = create_worker(WorkerSettings)
            await w.main()
        asyncio.run(run(), loop_factory=loop_factory)


if __name__ == "__main__":
    main()
