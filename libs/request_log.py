"""Server-side request timing middleware.

Records when each request started and ended, on the server, with the pid that
handled it. This is the authority for whether two actors were genuinely in
flight simultaneously -- client-side timestamps only show what the clients
believed.

Failures here are swallowed deliberately and only here: this is instrumentation,
and an instrumentation error must not change the behaviour of the system under
measurement. Every other error path in this codebase surfaces.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from starlette.types import ASGIApp, Receive, Scope, Send


class RequestLogMiddleware:
    def __init__(self, app: ASGIApp, connect) -> None:
        self.app = app
        self._connect = connect

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode(): v.decode() for k, v in scope.get("headers", [])}
        started = datetime.now(timezone.utc)
        row_id = self._insert(
            headers.get("x-actor-id"),
            headers.get("x-schedule-id"),
            scope.get("method", ""),
            scope.get("path", ""),
            started,
        )
        try:
            await self.app(scope, receive, send)
        finally:
            self._finish(row_id)

    def _insert(self, actor, schedule, method, path, started) -> int | None:
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO request_log "
                    "(actor_id, schedule_id, method, path, pid, started_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                    (actor, schedule, method, path, os.getpid(), started),
                )
                row_id = cur.fetchone()[0]
                conn.commit()
                return row_id
        except Exception:
            return None

    def _finish(self, row_id: int | None) -> None:
        if row_id is None:
            return
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(
                    "UPDATE request_log SET ended_at = %s WHERE id = %s",
                    (datetime.now(timezone.utc), row_id),
                )
                conn.commit()
        except Exception:
            pass
