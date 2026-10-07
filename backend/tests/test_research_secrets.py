"""Full-stack secret handling: a user's encrypted Groq key → the real gateway and Groq adapter
(over a mock HTTP transport) → a full graph run. The key must reach the provider's
Authorization header and nowhere else: not in graph state, not in any trace row."""

import json
import pickle

import httpx2
import pytest
from fastapi import FastAPI

from app.llm.factory import build_gateway_for_user, rate_limiters_from
from app.llm.types import LLMRequest, Message
from app.orchestration.runner import run_research
from app.schemas.contracts import ResearchRequest
from app.services.credentials import CredentialService
from tests.agent_fakes import (
    ScriptedLLM,
    make_paper,
    make_runtime,
    scripts,
    synthesis_reply,
    trace_rows,
)
from tests.llm_fakes import GROQ_TEST_KEY

pytestmark = pytest.mark.anyio


async def test_provider_key_never_enters_state_or_trace(app: FastAPI) -> None:
    scripted = ScriptedLLM(scripts([synthesis_reply("sufficient")]))
    authorizations: list[str] = []

    def groq_api(request: httpx2.Request) -> httpx2.Response:
        authorizations.append(request.headers["authorization"])
        body = json.loads(request.content)
        llm_request = LLMRequest(
            tuple(Message(m["role"], m["content"]) for m in body["messages"]), model=body["model"]
        )
        content = scripted.reply(llm_request)
        return httpx2.Response(
            200,
            json={
                "model": body["model"],
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            },
        )

    rt, _ = await make_runtime(
        app, scripted, lambda q: [make_paper("W1", "Sleep A"), make_paper("W2", "Sleep B")]
    )
    user_id = rt.recorder.user_id
    async with app.state.database.sessionmaker() as db, db.begin():
        await CredentialService(db, app.state.cipher).save(user_id, "groq", GROQ_TEST_KEY)
    settings = app.state.settings.model_copy(update={"groq_models": ["groq-test-model"]})
    async with app.state.database.sessionmaker() as db:
        rt.gateway = await build_gateway_for_user(
            db,
            user_id,
            cipher=app.state.cipher,
            settings=settings,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(groq_api)),
            limiters=rate_limiters_from(
                settings.model_copy(update={"groq_requests_per_minute": 1000})
            ),
        )

    state = await run_research(
        rt, ResearchRequest(question="How does sleep deprivation affect memory?")
    )
    assert state["status"] == "completed"
    assert authorizations and set(authorizations) == {f"Bearer {GROQ_TEST_KEY}"}  # the key was used

    state_dump = (
        repr(state)
        + pickle.dumps(state).hex()
        + json.dumps(
            {
                k: v.model_dump(mode="json") if hasattr(v, "model_dump") else repr(v)
                for k, v in state.items()
            },
            default=str,
        )
    )
    assert GROQ_TEST_KEY not in state_dump and GROQ_TEST_KEY.encode().hex() not in state_dump
    rows = json.dumps(await trace_rows(app, rt.recorder.run_id))
    assert GROQ_TEST_KEY not in rows and "Bearer" not in rows
