"""The credential boundary: stored (encrypted) user keys → provider adapters."""

import re
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI

from app.config import Settings
from app.llm.errors import NoProviderConfigured
from app.llm.factory import build_gateway_for_user, rate_limiters_from
from app.llm.gateway import LLMGateway
from app.schemas.contracts import ResearchRequest
from app.services.credential_crypto import CredentialCipher
from app.services.credentials import CredentialService
from tests.conftest import execute
from tests.llm_fakes import GEMINI_TEST_KEY, GROQ_TEST_KEY, Recorder, json_response

pytestmark = pytest.mark.anyio

VALID = '{"question": "How does sleep deprivation affect memory consolidation?"}'
GROQ_OK = {"choices": [{"message": {"content": VALID}, "finish_reason": "stop"}], "usage": {}}
GEMINI_OK = {"candidates": [{"content": {"parts": [{"text": VALID}]}, "finishReason": "STOP"}]}


async def _user_with_keys(app: FastAPI, **keys: str) -> uuid.UUID:
    user_id = uuid.uuid4()
    await execute(
        app,
        "INSERT INTO users (id, email, password_hash) VALUES (:id, :email, 'x')",
        id=user_id,
        email=f"{user_id}@example.com",
    )
    async with app.state.database.sessionmaker() as db, db.begin():
        service = CredentialService(db, app.state.cipher)
        for provider, key in keys.items():
            await service.save(user_id, provider, key)
    return user_id


async def _gateway(app: FastAPI, user_id: uuid.UUID, recorder: Recorder) -> LLMGateway:
    settings: Settings = app.state.settings.model_copy(
        update={"groq_models": ["groq-test-model"], "gemini_models": ["gemini-test-model"]}
    )
    async with app.state.database.sessionmaker() as db:
        return await build_gateway_for_user(
            db,
            user_id,
            cipher=app.state.cipher,
            settings=settings,
            http_client=recorder.client(),
            limiters=rate_limiters_from(settings),
        )


async def test_groq_only_user_gets_working_gateway_with_decrypted_key(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = await _user_with_keys(app, groq=GROQ_TEST_KEY)
    recorder = Recorder(json_response(200, GROQ_OK), json_response(200, GROQ_OK))
    gw = await _gateway(app, user_id, recorder)
    assert gw.available == ("groq",)

    # Decryption goes through the Phase 3 cipher, once per request, at request time.
    decrypts = 0
    original = CredentialCipher.decrypt

    def counting_decrypt(self: CredentialCipher, token: bytes) -> str:
        nonlocal decrypts
        decrypts += 1
        return original(self, token)

    monkeypatch.setattr(CredentialCipher, "decrypt", counting_decrypt)
    assert decrypts == 0  # building the gateway decrypted nothing

    await gw.generate_structured(ResearchRequest, [], role="synthesis")
    await gw.generate_structured(ResearchRequest, [], role="writer")
    assert decrypts == 2
    assert [r.headers["authorization"] for r in recorder.requests] == [
        f"Bearer {GROQ_TEST_KEY}"
    ] * 2

    # The plaintext is not retained anywhere on the gateway or its providers.
    state = repr(vars(gw)) + "".join(repr(vars(p)) for p in vars(gw)["_providers"].values())
    assert GROQ_TEST_KEY not in state


async def test_gemini_only_user(app: FastAPI) -> None:
    user_id = await _user_with_keys(app, gemini=GEMINI_TEST_KEY)
    recorder = Recorder(json_response(200, GEMINI_OK))
    gw = await _gateway(app, user_id, recorder)
    assert gw.available == ("gemini",)
    await gw.generate_structured(ResearchRequest, [], role="planner")
    assert recorder.requests[0].headers["x-goog-api-key"] == GEMINI_TEST_KEY


async def test_both_providers(app: FastAPI) -> None:
    user_id = await _user_with_keys(app, groq=GROQ_TEST_KEY, gemini=GEMINI_TEST_KEY)
    gw = await _gateway(app, user_id, Recorder())
    assert gw.available == ("groq", "gemini")
    assert gw.candidates("writer")[0].provider == "gemini"


async def test_user_without_keys_fails_clearly_on_first_call(app: FastAPI) -> None:
    user_id = await _user_with_keys(app)
    gw = await _gateway(app, user_id, Recorder())
    with pytest.raises(NoProviderConfigured):
        await gw.generate_structured(ResearchRequest, [])


async def test_keys_marked_invalid_are_skipped(app: FastAPI) -> None:
    user_id = await _user_with_keys(app, groq=GROQ_TEST_KEY, gemini=GEMINI_TEST_KEY)
    await execute(
        app,
        "UPDATE user_provider_credentials SET status = 'invalid' "
        "WHERE user_id = :u AND provider = 'groq'",
        u=user_id,
    )
    gw = await _gateway(app, user_id, Recorder())
    assert gw.available == ("gemini",)


async def test_users_get_only_their_own_keys(app: FastAPI) -> None:
    alice = await _user_with_keys(app, groq=GROQ_TEST_KEY)
    bob = await _user_with_keys(app)
    gw = await _gateway(app, bob, Recorder())
    assert gw.available == ()
    assert (await _gateway(app, alice, Recorder())).available == ("groq",)


def test_llm_layer_does_not_duplicate_encryption() -> None:
    """Decryption lives only in app/services/credential_crypto.py (Phase 3)."""
    llm_dir = Path(__file__).resolve().parents[1] / "app" / "llm"
    for source in llm_dir.glob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert not re.search(r"cryptography|Fernet|\.decrypt\(", text), source.name
