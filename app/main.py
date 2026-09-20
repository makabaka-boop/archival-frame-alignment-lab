"""Pure-backend HTTP API for film-scan correspondence repair.

Endpoints
---------
POST /api/projects          submit the two scan arrays; returns the global
                            optimal correspondence
GET  /api/projects/{id}     fetch a stored project (survives API restarts)
PUT  /api/projects/{id}/anchors
                            replace the anchor set and recompute; illegal
                            anchors yield 422 and leave the state untouched
GET  /health                liveness probe

There are no stub/fake endpoints: every route performs the described work
against PostgreSQL.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from contextlib import asynccontextmanager
from typing import Any

import anyio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import db
from .solver import InvalidAnchors, solve, validate_anchors

MAX_ITEMS = 20_000
MAX_FP_LEN = 32
MAX_REPEATS = 4


def _unprocessable(detail: str) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": detail})


def _is_printable_ascii(value: Any) -> bool:
    if not isinstance(value, str) or not (1 <= len(value) <= MAX_FP_LEN):
        return False
    # Byte-wise, case sensitive, no normalisation.  ASCII printable means
    # every byte is in 0x20..0x7E.
    for ch in value:
        code = ord(ch)
        if code < 0x20 or code > 0x7E:
            return False
    return True


def _validate_scans(payload: Any) -> tuple[list[str], list[str]] | JSONResponse:
    if not isinstance(payload, dict) or "left" not in payload or "right" not in payload:
        return _unprocessable("body must be an object with 'left' and 'right' arrays")
    left, right = payload["left"], payload["right"]
    if not isinstance(left, list) or not isinstance(right, list):
        return _unprocessable("'left' and 'right' must be JSON string arrays")
    for name, side in (("left", left), ("right", right)):
        if not (1 <= len(side) <= MAX_ITEMS):
            return _unprocessable(
                f"'{name}' must contain between 1 and {MAX_ITEMS} items"
            )
        for fp in side:
            if not _is_printable_ascii(fp):
                return _unprocessable(
                    f"every fingerprint must be a 1..{MAX_FP_LEN} char printable "
                    "ASCII string"
                )
        repeats = Counter(side)
        if repeats and repeats.most_common(1)[0][1] > MAX_REPEATS:
            return _unprocessable(
                f"each fingerprint may appear at most {MAX_REPEATS} times per side"
            )
    return left, right


def _validate_anchor_payload(
    payload: Any, left: list[str], right: list[str]
) -> list[list[int]] | JSONResponse:
    if not isinstance(payload, dict) or "anchors" not in payload:
        return _unprocessable("body must be an object with an 'anchors' array")
    raw_anchors = payload["anchors"]
    if not isinstance(raw_anchors, list):
        return _unprocessable("'anchors' must be an array of [i, j] pairs")
    pairs: list[list[int]] = []
    for pair in raw_anchors:
        if not isinstance(pair, list) or len(pair) != 2:
            return _unprocessable("every anchor must be a [i, j] pair")
        i, j = pair
        if isinstance(i, bool) or isinstance(j, bool) or not (
            isinstance(i, int) and isinstance(j, int)
        ):
            return _unprocessable("anchor indices must be integers")
        pairs.append([i, j])
    try:
        chain = validate_anchors(pairs, left, right)
    except InvalidAnchors as exc:
        return _unprocessable(str(exc))
    return [list(p) for p in chain]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # The database container may still be initialising on a cold compose up.
    last_error: Exception | None = None
    for _ in range(30):
        try:
            _app.state.pool = await db.init_db()
            break
        except Exception as exc:  # noqa: BLE001 - retry any startup failure
            last_error = exc
            await asyncio.sleep(1)
    else:
        raise RuntimeError(f"could not connect to PostgreSQL: {last_error}")
    try:
        yield
    finally:
        await db.close_db(_app.state.pool)


app = FastAPI(title="film-scan-correspondence", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/projects")
async def create_project(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        return _unprocessable("request body must be valid JSON")

    validated = _validate_scans(payload)
    if isinstance(validated, JSONResponse):
        return validated
    left, right = validated

    result = await anyio.to_thread.run_sync(solve, left, right, None)
    project_id = await db.create_project(
        app.state.pool, left, right, [], result
    )
    return JSONResponse(
        status_code=201,
        content={
            "id": project_id,
            "left": left,
            "right": right,
            "anchors": [],
            "result": result,
            "length": len(result),
        },
    )


def _project_response(project: dict[str, Any]) -> JSONResponse:
    return JSONResponse(status_code=200, content=project)


@app.get("/api/projects/{project_id}")
async def get_project(project_id: int) -> JSONResponse:
    project = await db.get_project(app.state.pool, project_id)
    if project is None:
        return JSONResponse(status_code=404, content={"detail": "project not found"})
    return _project_response(project)


@app.put("/api/projects/{project_id}/anchors")
async def replace_anchors(project_id: int, request: Request) -> JSONResponse:
    project = await db.get_project(app.state.pool, project_id)
    if project is None:
        return JSONResponse(status_code=404, content={"detail": "project not found"})

    try:
        payload = await request.json()
    except Exception:
        return _unprocessable("request body must be valid JSON")

    left, right = project["left"], project["right"]
    validated = _validate_anchor_payload(payload, left, right)
    if isinstance(validated, JSONResponse):
        return validated
    anchors = validated

    # Compute against the validated chain first; persistence only happens
    # afterwards, so an illegal chain leaves the stored state untouched.
    result = await anyio.to_thread.run_sync(solve, left, right, anchors)
    await db.replace_anchors(app.state.pool, project_id, anchors, result)
    return JSONResponse(
        status_code=200,
        content={
            "id": project_id,
            "left": left,
            "right": right,
            "anchors": anchors,
            "result": result,
            "length": len(result),
        },
    )
