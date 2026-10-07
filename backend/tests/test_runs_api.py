"""Runs API end to end: real HTTP API → background executor → real Phase 6 LangGraph → real
trace recorder and Postgres persistence. Only the LLM and the literature source are scripted."""

import asyncio
import json
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from httpx2 import AsyncClient
from sqlalchemy import text

from app.llm.factory import build_gateway_for_user, rate_limiters_from
from app.llm.types import LLMRequest, Message
from tests.agent_fakes import (
    ABSTRACT,
    SEARCH_REVISION,
    GatedLLM,
    ScriptedLLM,
    install_executor,
    make_paper,
    scripts,
    synthesis_reply,
    wait_for_run,
)
from tests.conftest import COOKIE_NAME, create_run, execute, make_client, register_and_login, scalar
from tests.llm_fakes import GROQ_TEST_KEY
from tests.test_research_graph import catalog_search_revision

pytestmark = pytest.mark.anyio

QUESTION = {"question": "How does sleep deprivation affect memory consolidation in adults?"}


def TWO_PAPERS(query: str) -> list[Any]:  # noqa: N802 - used like a constant catalogue
    return [make_paper("W1", "Sleep loss and recall"), make_paper("W2", "Sleep stages and memory")]


async def start(client: AsyncClient, body: dict[str, Any] | None = None) -> str:
    response = await client.post("/api/runs", json=body or QUESTION)
    assert response.status_code == 202, response.text
    return str(response.json()["id"])


async def events(client: AsyncClient, run_id: str) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    after = 0
    while True:
        page = (
            await client.get(f"/api/runs/{run_id}/events", params={"after": after, "limit": 200})
        ).json()
        if not page:
            return collected
        collected += page
        after = page[-1]["seq"]


def started(trace: list[dict[str, Any]]) -> list[str]:
    return [e["agent"] for e in trace if e["event_type"] == "agent_started"]


# ---------------- auth, validation, ownership ----------------


async def test_run_endpoints_require_authentication(client: AsyncClient) -> None:
    for method, path in [
        ("POST", "/api/runs"),
        ("GET", "/api/runs"),
        ("GET", "/api/runs/00000000-0000-0000-0000-000000000000"),
        ("GET", "/api/runs/00000000-0000-0000-0000-000000000000/result"),
        ("GET", "/api/runs/00000000-0000-0000-0000-000000000000/events"),
    ]:
        response = await client.request(method, path, json=QUESTION if method == "POST" else None)
        assert response.status_code == 401, path


async def test_invalid_research_request_is_rejected_by_the_contract(
    client: AsyncClient, app: FastAPI
) -> None:
    install_executor(app, ScriptedLLM(scripts([synthesis_reply("sufficient")])), TWO_PAPERS)
    await register_and_login(client)
    for body in (
        {"question": "too short"},
        {"question": QUESTION["question"], "max_iterations": 9},
        {},
    ):
        response = await client.post("/api/runs", json=body)
        assert response.status_code == 422
        assert "too short" not in response.text  # inputs are never echoed
    assert await scalar(app, "SELECT count(*) FROM runs") == 0


async def test_runs_are_private_to_their_owner(app: FastAPI) -> None:
    install_executor(app, ScriptedLLM(scripts([synthesis_reply("sufficient")])), TWO_PAPERS)
    async with make_client(app) as alice, make_client(app) as bob:
        await register_and_login(alice, "alice@example.com")
        await register_and_login(bob, "bob@example.com")
        run_id = await start(alice)
        await wait_for_run(alice, run_id)

        for path in ("", "/result", "/events", "/outputs"):
            assert (await bob.get(f"/api/runs/{run_id}{path}")).status_code == 404
        assert (await bob.post(f"/api/runs/{run_id}/cancel")).status_code == 404
        assert (await bob.get("/api/runs")).json()["total"] == 0
        assert (await alice.get("/api/runs")).json()["total"] == 1


# ---------------- deterministic end to end ----------------


async def test_end_to_end_run_through_the_api(client: AsyncClient, app: FastAPI) -> None:
    install_executor(app, ScriptedLLM(scripts([synthesis_reply("sufficient")])), TWO_PAPERS)
    await register_and_login(client)

    created = await client.post("/api/runs", json=QUESTION)
    assert created.status_code == 202
    assert (
        created.json()["status"] == "queued" and created.json()["progress"]["max_iterations"] == 3
    )
    run_id = created.json()["id"]

    detail = await wait_for_run(client, run_id)
    assert detail["status"] == "completed" and detail["stop_reason"] == "sufficient"
    assert detail["started_at"] and detail["completed_at"] and detail["error"] is None
    assert detail["progress"]["llm_calls"] > 0 and detail["progress"]["tokens_used"] > 0
    assert detail["request"]["question"] == QUESTION["question"]

    result = (await client.get(f"/api/runs/{run_id}/result")).json()
    assert result["status"] == "completed" and result["review"]["evidence_status"] == "sufficient"
    assert {r["citation_key"] for r in result["review"]["references"]} == {"P1", "P2"}
    assert result["synthesis"]["verdict"] == "sufficient"

    trace = await events(client, run_id)
    assert started(trace) == ["planner", "search", "analysis", "synthesis", "writer"]
    assert [e["seq"] for e in trace] == list(range(1, len(trace) + 1))
    assert trace[0]["event_type"] == "run_started" and trace[-1]["event_type"] == "run_completed"

    outputs = (await client.get(f"/api/runs/{run_id}/outputs")).json()
    assert [o["schema_name"] for o in outputs] == [
        "research_plan",
        "search_request",
        "search_results",
        "document_analysis",
        "document_analysis",
        "synthesis_decision",
        "final_review",
    ]
    # Trace completion events point at the persisted outputs.
    refs = {e["output_ref"] for e in trace if e["event_type"] == "agent_completed"} - {None}
    assert refs <= {o["id"] for o in outputs} and len(refs) == 5


async def test_adaptive_loop_through_the_api(client: AsyncClient, app: FastAPI) -> None:
    """POST /api/runs → Planner → Search → Analysis → Synthesis(insufficient) →
    Replanning(search_revision) → Search → Analysis → Synthesis(sufficient) → Writer → completed."""
    llm = ScriptedLLM(
        scripts(
            [
                synthesis_reply("insufficient", replanning=SEARCH_REVISION),
                synthesis_reply("sufficient"),
            ]
        )
    )
    install_executor(app, llm, catalog_search_revision, missing_pdfs={"W3"})
    await register_and_login(client)
    run_id = await start(client)
    detail = await wait_for_run(client, run_id)
    assert detail["status"] == "completed" and detail["iteration"] == 2

    trace = await events(client, run_id)
    assert started(trace) == [
        "planner",
        "search",
        "analysis",
        "synthesis",
        "orchestrator",
        "search",
        "analysis",
        "synthesis",
        "writer",
    ]
    verdicts = [
        e["decision"]["route"]
        for e in trace
        if e["event_type"] == "decision" and e["agent"] == "synthesis"
    ]
    assert verdicts == ["insufficient", "sufficient"]
    assert [e["decision"]["route"] for e in trace if e["event_type"] == "replan"] == [
        "search_revision"
    ]

    by_iteration: dict[int, list[str]] = {}
    for o in (await client.get(f"/api/runs/{run_id}/outputs")).json():
        by_iteration.setdefault(o["iteration"], []).append(o["schema_name"])
    assert (
        "replanning_request" in by_iteration[1] and by_iteration[1].count("synthesis_decision") == 1
    )
    assert (
        by_iteration[2][:2] == ["search_request", "search_results"]
        and "final_review" in by_iteration[2]
    )
    second = (
        await client.get(f"/api/runs/{run_id}/outputs", params={"agent": "search", "iteration": 2})
    ).json()
    queries = [q["query"] for q in second[1]["payload"]["queries_executed"]]
    assert (
        "sleep stages memory consolidation" in queries
    )  # the revision searched what synthesis asked


# ---------------- lifecycle and statuses ----------------


async def test_lifecycle_queued_running_completed_with_bounded_concurrency(app: FastAPI) -> None:
    gate = asyncio.Event()
    install_executor(
        app, GatedLLM(scripts([synthesis_reply("sufficient")]), gate), TWO_PAPERS, max_concurrent=1
    )
    async with make_client(app) as alice, make_client(app) as bob:
        await register_and_login(alice, "alice@example.com")
        await register_and_login(bob, "bob@example.com")
        first = await start(alice)
        await wait_for_run(alice, first, until=("running",))
        second = await start(bob)
        await asyncio.sleep(0.1)
        assert (await bob.get(f"/api/runs/{second}")).json()["status"] == "queued"  # one slot only
        assert (await alice.get(f"/api/runs/{first}/result")).status_code == 409  # not finished

        gate.set()
        assert (await wait_for_run(alice, first))["status"] == "completed"
        assert (await wait_for_run(bob, second))["status"] == "completed"


async def test_one_active_run_per_user(client: AsyncClient, app: FastAPI) -> None:
    gate = asyncio.Event()
    install_executor(app, GatedLLM(scripts([synthesis_reply("sufficient")]), gate), TWO_PAPERS)
    await register_and_login(client)
    run_id = await start(client)
    assert (await client.post("/api/runs", json=QUESTION)).status_code == 409
    gate.set()
    await wait_for_run(client, run_id)
    assert (await client.post("/api/runs", json=QUESTION)).status_code == 202


async def test_no_provider_fails_the_run_safely(client: AsyncClient, app: FastAPI) -> None:
    install_executor(app, None, TWO_PAPERS)
    await register_and_login(client)
    run_id = await start(client)
    detail = await wait_for_run(client, run_id)
    assert detail["status"] == "failed"
    assert (
        detail["error"]["code"] == "no_provider_configured" and detail["error"]["node"] == "planner"
    )
    result = await client.get(f"/api/runs/{run_id}/result")
    assert result.status_code == 200 and result.json()["review"] is None
    assert result.json()["error"]["code"] == "no_provider_configured"


async def test_writer_failure_leaves_a_partial_run_with_synthesis(
    client: AsyncClient, app: FastAPI
) -> None:
    invented = json.dumps(
        {
            "title": "T",
            "abstract": "A",
            "sections": [{"heading": "H", "kind": "body", "body_markdown": "x [@X9]."}],
        }
    )
    install_executor(
        app,
        ScriptedLLM(scripts([synthesis_reply("sufficient")], ReviewDraft=[invented, invented])),
        TWO_PAPERS,
    )
    await register_and_login(client)
    run_id = await start(client)
    detail = await wait_for_run(client, run_id)
    assert detail["status"] == "partial" and detail["error"]["node"] == "review_writer"
    result = (await client.get(f"/api/runs/{run_id}/result")).json()
    assert result["review"] is None and result["synthesis"]["verdict"] == "sufficient"


async def test_iteration_limit_is_persisted_as_completed_with_limitations(
    client: AsyncClient, app: FastAPI
) -> None:
    counter = iter(range(100))
    install_executor(
        app,
        ScriptedLLM(scripts([synthesis_reply("insufficient", replanning=SEARCH_REVISION)])),
        lambda q: [
            make_paper(
                f"W{200 + next(counter)}", f"Abstract-only {q}", pdf=False, abstract=ABSTRACT
            )
        ],
    )
    await register_and_login(client)
    run_id = await start(client)
    detail = await wait_for_run(client, run_id)
    assert detail["status"] == "completed_with_limitations"
    assert detail["stop_reason"] == "iteration_limit" and detail["iteration"] == 3
    review = (await client.get(f"/api/runs/{run_id}/result")).json()["review"]
    assert review["evidence_status"] == "limited" and review["limitations"]
    stored = await scalar(app, "SELECT status FROM runs WHERE id = :r", r=run_id)
    assert stored == "completed_with_limitations"


async def test_cancel_a_running_run(client: AsyncClient, app: FastAPI) -> None:
    gate = asyncio.Event()
    install_executor(app, GatedLLM(scripts([synthesis_reply("sufficient")]), gate), TWO_PAPERS)
    await register_and_login(client)
    run_id = await start(client)
    await wait_for_run(client, run_id, until=("running",))
    assert (await client.post(f"/api/runs/{run_id}/cancel")).status_code == 202
    detail = await wait_for_run(client, run_id)
    assert detail["status"] == "cancelled" and detail["error"]["code"] == "cancelled"
    assert (await client.post(f"/api/runs/{run_id}/cancel")).status_code == 409
    trace = await events(client, run_id)
    assert trace[-1]["event_type"] == "run_completed" and trace[-1]["message"] == "run cancelled"


async def test_startup_sweep_marks_interrupted_runs_failed(
    client: AsyncClient, app: FastAPI
) -> None:
    await register_and_login(client)
    user_id = (await client.get("/api/auth/me")).json()["id"]
    run_id = await create_run(app, user_id, status="running")
    assert await app.state.run_executor.sweep_interrupted() == 1
    detail = (await client.get(f"/api/runs/{run_id}")).json()
    assert detail["status"] == "failed" and detail["error"]["code"] == "interrupted"


async def test_list_runs_paginates_newest_first(client: AsyncClient, app: FastAPI) -> None:
    await register_and_login(client)
    user_id = (await client.get("/api/auth/me")).json()["id"]
    ids = [str(await create_run(app, user_id, status="completed")) for _ in range(3)]
    first = (await client.get("/api/runs", params={"limit": 2})).json()
    second = (await client.get("/api/runs", params={"limit": 2, "offset": 2})).json()
    assert first["total"] == 3 and len(first["items"]) == 2 and len(second["items"]) == 1
    assert {i["id"] for i in first["items"] + second["items"]} == set(ids)
    assert set(first["items"][0]) == {
        "id",
        "question",
        "status",
        "iteration",
        "stop_reason",
        "created_at",
        "updated_at",
        "completed_at",
    }  # metadata only: no review, no trace
    assert (await client.get("/api/runs", params={"limit": 500})).status_code == 422


async def test_deleting_a_run_cascades_through_the_append_only_trace(
    client: AsyncClient, app: FastAPI
) -> None:
    install_executor(app, ScriptedLLM(scripts([synthesis_reply("sufficient")])), TWO_PAPERS)
    await register_and_login(client)
    run_id = await start(client)
    await wait_for_run(client, run_id)
    before = await scalar(app, "SELECT count(*) FROM trace_events WHERE run_id = :r", r=run_id)
    assert isinstance(before, int) and before > 0
    await execute(app, "DELETE FROM runs WHERE id = :r", r=run_id)
    assert await scalar(app, "SELECT count(*) FROM trace_events WHERE run_id = :r", r=run_id) == 0
    assert await scalar(app, "SELECT count(*) FROM agent_outputs WHERE run_id = :r", r=run_id) == 0


# ---------------- credentials and secrets ----------------


def _groq_api(scripted: ScriptedLLM, *, status: int = 200) -> httpx2.AsyncClient:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if status != 200:
            return httpx2.Response(status, json={"error": {"message": "Invalid API Key"}})
        body = json.loads(request.content)
        content = scripted.reply(
            LLMRequest(
                tuple(Message(m["role"], m["content"]) for m in body["messages"]),
                model=body["model"],
            )
        )
        return httpx2.Response(
            200,
            json={
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 90, "completion_tokens": 40},
            },
        )

    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


def _real_gateway_factory(app: FastAPI, provider_client: httpx2.AsyncClient) -> Any:
    settings = app.state.settings.model_copy(
        update={"groq_models": ["groq-test-model"], "groq_requests_per_minute": 1000}
    )

    async def factory(db: Any, user_id: Any) -> Any:
        return await build_gateway_for_user(
            db,
            user_id,
            cipher=app.state.cipher,
            settings=settings,
            http_client=provider_client,
            limiters=rate_limiters_from(settings),
        )

    return factory


async def test_no_secret_reaches_runs_outputs_trace_or_responses(
    client: AsyncClient, app: FastAPI
) -> None:
    scripted = ScriptedLLM(scripts([synthesis_reply("sufficient")]))
    install_executor(
        app, scripted, TWO_PAPERS, gateway_factory=_real_gateway_factory(app, _groq_api(scripted))
    )
    await register_and_login(client)
    assert (
        await client.put("/api/credentials/groq", json={"api_key": GROQ_TEST_KEY})
    ).status_code == 200
    run_id = await start(client)
    assert (await wait_for_run(client, run_id))["status"] == "completed"

    session_token = client.cookies[COOKIE_NAME]
    password_hash = str(await scalar(app, "SELECT password_hash FROM users"))
    responses = ""
    for path in ("", "/result", "/events?limit=200", "/outputs"):
        responses += (await client.get(f"/api/runs/{run_id}{path}")).text
    responses += (await client.get("/api/runs")).text
    tables = ""
    for query in (
        "SELECT row_to_json(t)::text FROM runs t",
        "SELECT row_to_json(t)::text FROM agent_outputs t",
        "SELECT row_to_json(t)::text FROM trace_events t",
    ):
        async with app.state.database.engine.connect() as conn:
            tables += "".join((await conn.execute(text(query))).scalars().all())
    for secret in (GROQ_TEST_KEY, session_token, password_hash, "Bearer "):
        assert secret not in responses and secret not in tables


async def test_provider_auth_failure_marks_the_key_invalid(
    client: AsyncClient, app: FastAPI
) -> None:
    scripted = ScriptedLLM(scripts([synthesis_reply("sufficient")]))
    install_executor(
        app,
        scripted,
        TWO_PAPERS,
        gateway_factory=_real_gateway_factory(app, _groq_api(scripted, status=401)),
    )
    await register_and_login(client)
    await client.put("/api/credentials/groq", json={"api_key": GROQ_TEST_KEY})
    run_id = await start(client)
    detail = await wait_for_run(client, run_id)
    assert detail["status"] == "failed" and detail["error"]["code"] == "auth_failed"
    assert GROQ_TEST_KEY not in json.dumps(detail)
    credentials = {c["provider"]: c for c in (await client.get("/api/credentials")).json()}
    assert credentials["groq"]["status"] == "invalid"


@pytest.mark.parametrize(
    ("provider_status", "expected"), [(200, "valid"), (401, "invalid"), (503, "unverified")]
)
async def test_key_is_checked_when_saved(
    client: AsyncClient, app: FastAPI, provider_status: int, expected: str
) -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(provider_status, json={})

    app.state.settings = app.state.settings.model_copy(
        update={"validate_credentials_on_save": True}
    )
    app.state.http_client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    await register_and_login(client)
    response = await client.put("/api/credentials/groq", json={"api_key": GROQ_TEST_KEY})
    assert response.json()["status"] == expected and GROQ_TEST_KEY not in response.text
    assert str(seen[0].url) == "https://api.groq.com/openai/v1/models"
    assert seen[0].headers["authorization"] == f"Bearer {GROQ_TEST_KEY}"
