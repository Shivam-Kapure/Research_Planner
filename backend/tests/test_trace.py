import asyncio
import json
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx2 import AsyncClient
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.llm.gateway import AttemptRecord
from app.services.trace_recorder import TraceRecorder
from tests.conftest import COOKIE_NAME, make_client, register_and_login, scalar
from tests.llm_fakes import GEMINI_TEST_KEY, GROQ_TEST_KEY

pytestmark = pytest.mark.anyio


async def _user(client: AsyncClient, email: str = "alice@example.com") -> uuid.UUID:
    await register_and_login(client, email)
    return uuid.UUID((await client.get("/api/auth/me")).json()["id"])


def _recorder(app: FastAPI, user_id: uuid.UUID, run_id: uuid.UUID | None = None) -> TraceRecorder:
    return TraceRecorder(
        app.state.database.sessionmaker, run_id=run_id or uuid.uuid4(), user_id=user_id
    )


async def _rows(app: FastAPI, run_id: uuid.UUID) -> list[dict[str, Any]]:
    async with app.state.database.engine.connect() as conn:
        result = await conn.execute(
            text("SELECT row_to_json(t)::text FROM trace_events t WHERE run_id = :r ORDER BY seq"),
            {"r": run_id},
        )
        return [json.loads(row[0]) for row in result]


# ---- appending ----


async def test_events_are_appended_with_gap_free_sequence(
    client: AsyncClient, app: FastAPI
) -> None:
    rec = _recorder(app, await _user(client))
    started = await rec.agent_started("planner", iteration=1, message="planning")
    await rec.llm_call(
        "planner",
        iteration=1,
        parent_id=started.id,
        attempt=AttemptRecord("groq", "m", 1, "initial", "ok", 120, 300, 80),
    )
    await rec.tool_call(
        "search", iteration=1, name="search_openalex", args={"query": "sleep memory"}
    )
    await rec.decision(
        "synthesis",
        iteration=1,
        route="insufficient",
        rationale="sq-2 weak",
        to_agent="search",
        event_type="replan",
    )
    done = await rec.agent_completed("planner", iteration=1, message="done", parent_id=started.id)

    assert (started.seq, done.seq) == (1, 5)
    rows = await _rows(app, rec.run_id)
    assert [r["seq"] for r in rows] == [1, 2, 3, 4, 5]
    assert [r["event_type"] for r in rows] == [
        "agent_started",
        "llm_call",
        "tool_call",
        "replan",
        "agent_completed",
    ]
    assert rows[1]["parent_id"] == str(started.id)
    assert rows[1]["llm"] == {
        "provider": "groq",
        "model": "m",
        "attempt": 1,
        "kind": "initial",
        "outcome": "ok",
        "tokens_in": 300,
        "tokens_out": 80,
        "latency_ms": 120,
        "error_code": None,
    }
    assert rows[0]["tool"] is None  # absent payloads are SQL NULL
    assert rows[3]["decision"]["to_agent"] == "search"


async def test_concurrent_appends_get_unique_ordered_sequence(
    client: AsyncClient, app: FastAPI
) -> None:
    rec = _recorder(app, await _user(client))
    results = await asyncio.gather(
        *(rec.agent_started("analysis", iteration=1, message=f"paper {i}") for i in range(20))
    )
    assert sorted(r.seq for r in results) == list(range(1, 21))
    assert [r["seq"] for r in await _rows(app, rec.run_id)] == list(range(1, 21))


async def test_runs_have_independent_sequences_and_reopen_continues(
    client: AsyncClient, app: FastAPI
) -> None:
    user_id = await _user(client)
    run_a, run_b = uuid.uuid4(), uuid.uuid4()
    await _recorder(app, user_id, run_a).agent_started("planner", iteration=1, message="a")
    # A new recorder for the same run (e.g. after a restart) continues the sequence.
    rec_a = await TraceRecorder.open(app.state.database.sessionmaker, run_id=run_a, user_id=user_id)
    assert (await rec_a.agent_started("search", iteration=1, message="a2")).seq == 2
    rec_b = _recorder(app, user_id, run_b)
    assert (await rec_b.agent_started("planner", iteration=1, message="b")).seq == 1


@pytest.mark.parametrize(
    "event",
    [
        {"agent": "search", "event_type": "tool_call", "message": "no tool payload"},
        {
            "agent": "planner",
            "event_type": "error",
            "status": "ok",
            "message": "x",
            "error": {"code": "c", "message": "m", "retryable": False},
        },
        {"agent": "hacker", "event_type": "decision", "message": "x"},
        {"agent": "planner", "event_type": "teleport", "message": "x"},
        {"agent": "planner", "event_type": "agent_started", "message": "x", "iteration": -1},
        {"agent": "planner", "event_type": "agent_started", "message": "x", "surprise": 1},
    ],
)
async def test_invalid_events_are_rejected_and_not_persisted(
    client: AsyncClient, app: FastAPI, event: dict[str, object]
) -> None:
    rec = _recorder(app, await _user(client))
    with pytest.raises(ValidationError):
        await rec.record(event)
    assert await _rows(app, rec.run_id) == []


# ---- append-only ----


async def test_database_rejects_update_and_direct_delete(client: AsyncClient, app: FastAPI) -> None:
    rec = _recorder(app, await _user(client))
    await rec.agent_started("planner", iteration=1, message="original")

    for statement in (
        "UPDATE trace_events SET message = 'rewritten' WHERE run_id = :r",
        "DELETE FROM trace_events WHERE run_id = :r",
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            async with app.state.database.engine.begin() as conn:
                await conn.execute(text(statement), {"r": rec.run_id})
    rows = await _rows(app, rec.run_id)
    assert len(rows) == 1 and rows[0]["message"] == "original"
    assert not any(hasattr(rec, name) for name in ("update", "delete", "edit", "remove"))


async def test_deleting_the_user_cascades_to_their_trace(client: AsyncClient, app: FastAPI) -> None:
    user_id = await _user(client)
    rec = _recorder(app, user_id)
    parent = await rec.agent_started("planner", iteration=1, message="p")
    await rec.agent_completed("planner", iteration=1, message="c", parent_id=parent.id)
    async with app.state.database.engine.begin() as conn:
        await conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": user_id})
    assert await _rows(app, rec.run_id) == []


# ---- sanitisation ----


async def test_secrets_never_reach_trace_rows(client: AsyncClient, app: FastAPI) -> None:
    user_id = await _user(client)
    session_token = client.cookies[COOKIE_NAME]
    password_hash = str(
        await scalar(app, "SELECT password_hash FROM users WHERE id = :u", u=user_id)
    )
    ciphertext = app.state.cipher.encrypt(GROQ_TEST_KEY).decode()
    db_url = "postgresql+asyncpg://researchpilot:db-password-123@db.internal:5432/app"
    s2_paper_id = "649def34f8be52c8b66281af98ae884c09aef38b"
    paper_uuid = str(uuid.uuid4())
    secrets = [
        GROQ_TEST_KEY,
        GEMINI_TEST_KEY,
        session_token,
        password_hash,
        ciphertext,
        "db-password-123",
    ]

    rec = _recorder(app, user_id)
    await rec.tool_call(
        "search",
        iteration=1,
        name="search_semantic_scholar",
        args={
            "query": "sleep and memory",
            "paper_id": s2_paper_id,
            "headers": {
                "Authorization": f"Bearer {GROQ_TEST_KEY}",
                "Cookie": f"rp_session={session_token}",
            },
            "x-goog-api-key": GEMINI_TEST_KEY,
            "note": f"retrying with key {GEMINI_TEST_KEY}",
        },
        result_summary=f"selected {paper_uuid}",
    )
    await rec.error(
        "analysis",
        iteration=1,
        code="db_error",
        message=f"could not connect to {db_url} with session {session_token}",
        retryable=True,
    )
    await rec.validation(
        "writer",
        iteration=1,
        schema_name="final_review",
        passed=False,
        errors=[f"bad token {ciphertext}"],
        raw_excerpt=f"{{'hash': '{password_hash}', 'text': 'Sleep loss impairs recall.'}}",
    )
    await rec.record(
        {"agent": "orchestrator", "event_type": "run_started", "message": f"key={GROQ_TEST_KEY}"}
    )

    dump = json.dumps(await _rows(app, rec.run_id))
    for secret in secrets:
        assert secret not in dump
    # Research content and identifiers survive redaction.
    for kept in (
        "sleep and memory",
        s2_paper_id,
        paper_uuid,
        "Sleep loss impairs recall.",
        "db.internal",
    ):
        assert kept in dump


async def test_trace_payloads_are_size_bounded(client: AsyncClient, app: FastAPI) -> None:
    rec = _recorder(app, await _user(client))
    await rec.validation(
        "analysis",
        iteration=1,
        schema_name="document_analysis",
        passed=False,
        errors=["e"] * 200,
        raw_excerpt="x" * 50_000,
    )
    await rec.record({"agent": "planner", "event_type": "agent_started", "message": "m" * 10_000})
    await rec.tool_call(
        "search", iteration=1, name="t", args={f"k{i}": "v" * 5000 for i in range(200)}
    )

    validation, started, tool = await _rows(app, rec.run_id)
    assert len(validation["validation"]["raw_excerpt"]) <= 2000
    assert len(validation["validation"]["errors"]) == 50
    assert len(str(started["message"])) <= 500
    args = tool["tool"]["args"]
    assert len(args) == 50 and all(len(v) <= 1000 for v in args.values())


# ---- read API ----


async def test_owner_reads_events_in_order_with_cursor(client: AsyncClient, app: FastAPI) -> None:
    rec = _recorder(app, await _user(client))
    for i in range(5):
        await rec.agent_started("planner", iteration=1, message=f"step {i}")

    first = (await client.get(f"/api/runs/{rec.run_id}/events", params={"limit": 2})).json()
    assert [e["seq"] for e in first] == [1, 2]
    rest = (await client.get(f"/api/runs/{rec.run_id}/events", params={"after": 2})).json()
    assert [e["seq"] for e in rest] == [3, 4, 5]
    assert set(rest[0]) >= {"id", "run_id", "seq", "ts", "agent", "event_type", "status", "message"}
    assert "user_id" not in rest[0]
    empty = await client.get(f"/api/runs/{rec.run_id}/events", params={"after": 5})
    assert empty.status_code == 200 and empty.json() == []


async def test_trace_read_is_owner_only(app: FastAPI) -> None:
    async with make_client(app) as alice, make_client(app) as bob, make_client(app) as anon:
        rec = _recorder(app, await _user(alice, "alice@example.com"))
        await rec.agent_started("planner", iteration=1, message="private")
        await _user(bob, "bob@example.com")

        path = f"/api/runs/{rec.run_id}/events"
        assert (await alice.get(path)).status_code == 200
        assert (await bob.get(path)).status_code == 404
        assert (await bob.get(f"/api/runs/{uuid.uuid4()}/events")).status_code == 404
        assert (await anon.get(path)).status_code == 401
