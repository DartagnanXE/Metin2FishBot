# -*- coding: utf-8 -*-
"""FastAPI app factory + route wiring for the telemetry/leaderboard API.

Why FastAPI+uvicorn (over a Go binary): the whole repo is Python and is reviewed
by Python eyes, pydantic gives STRICT schema validation for almost no code, and
the dependency surface (fastapi/uvicorn/pydantic) is small and lives in its own
container. The honor-system leaderboard does not justify a second language.

Hardening here: a small body-size guard (reject oversized POSTs early -- nginx
also caps this), API docs OFF in prod unless ENABLE_DOCS=1, and the DB is
initialised on startup. Endpoints: POST /submit, GET /leaderboard, /admin/*,
plus a /health for the container HEALTHCHECK.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from . import db
from .routes_submit import router as submit_router
from .routes_leaderboard import router as leaderboard_router
from .admin import router as admin_router

# Reject bodies larger than this before parsing (defense in depth with nginx
# client_max_body_size). The submit payload is tiny (well under 1 KB).
MAX_BODY_BYTES = int(os.environ.get('MAX_BODY_BYTES', '4096'))


@asynccontextmanager
async def _lifespan(app):
    # Initialise the DB (create tables/indexes) once on startup. Using the
    # lifespan handler instead of the deprecated @app.on_event('startup').
    db.init_db()
    yield


def create_app():
    enable_docs = os.environ.get('ENABLE_DOCS', '0') == '1'
    app = FastAPI(
        title='Metin2MultiTool Ranking API',
        version='1',
        docs_url='/docs' if enable_docs else None,
        redoc_url=None,
        openapi_url='/openapi.json' if enable_docs else None,
        lifespan=_lifespan,
    )

    @app.middleware('http')
    async def _limit_body(request: Request, call_next):
        # Cheap guard using Content-Length (nginx enforces the hard cap; this is
        # belt-and-braces so the app never buffers a huge body).
        cl = request.headers.get('content-length')
        if cl is not None:
            try:
                if int(cl) > MAX_BODY_BYTES:
                    return JSONResponse(status_code=413,
                                        content={'status': 'error',
                                                 'detail': 'payload_too_large'})
            except ValueError:
                pass
        return await call_next(request)

    @app.get('/health')
    async def health():
        return PlainTextResponse('ok')

    app.include_router(submit_router)
    app.include_router(leaderboard_router)
    app.include_router(admin_router)
    return app


app = create_app()
