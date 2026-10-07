import logging

import pytest
from fastapi import FastAPI
from httpx2 import AsyncClient

from app.services.credential_crypto import CredentialCipher
from tests.conftest import make_client, register_and_login, scalar

pytestmark = pytest.mark.anyio

# Shaped like real keys but fake; each must never leave the backend in plaintext.
GROQ_KEY = "gsk_TESTONLY_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
GEMINI_KEY = "AIza-TESTONLY-not-a-real-key-0000"


async def _save(client: AsyncClient, provider: str, key: str) -> dict[str, object]:
    r = await client.put(f"/api/credentials/{provider}", json={"api_key": key})
    assert r.status_code == 200, r.text
    assert key not in r.text
    body: dict[str, object] = r.json()
    return body


async def test_save_groq_and_gemini_and_list_metadata_only(client: AsyncClient) -> None:
    await register_and_login(client)
    groq = await _save(client, "groq", GROQ_KEY)
    assert groq["configured"] is True
    assert groq["key_hint"] == GROQ_KEY[-4:]
    assert groq["status"] == "unverified"
    await _save(client, "gemini", GEMINI_KEY)

    r = await client.get("/api/credentials")
    assert r.status_code == 200
    assert GROQ_KEY not in r.text and GEMINI_KEY not in r.text
    by_provider = {c["provider"]: c for c in r.json()}
    assert set(by_provider) == {"groq", "gemini"}
    assert all(c["configured"] for c in by_provider.values())
    assert all("api_key" not in c and "ciphertext" not in c for c in by_provider.values())


async def test_database_holds_only_ciphertext(client: AsyncClient, app: FastAPI) -> None:
    await register_and_login(client)
    await _save(client, "groq", GROQ_KEY)

    row_text = await scalar(app, "SELECT row_to_json(c)::text FROM user_provider_credentials c")
    assert isinstance(row_text, str) and GROQ_KEY not in row_text
    ciphertext = await scalar(app, "SELECT ciphertext FROM user_provider_credentials")
    assert isinstance(ciphertext, bytes) and GROQ_KEY.encode() not in ciphertext
    # It is a real encryption under the configured key, not a hash or a placeholder.
    cipher: CredentialCipher = app.state.cipher
    assert cipher.decrypt(ciphertext) == GROQ_KEY


async def test_saving_again_replaces_the_single_record(client: AsyncClient, app: FastAPI) -> None:
    await register_and_login(client)
    await _save(client, "groq", GROQ_KEY)
    replacement = GROQ_KEY[:-4] + "ZZZZ"
    body = await _save(client, "groq", replacement)
    assert body["key_hint"] == "ZZZZ"
    assert await scalar(app, "SELECT count(*) FROM user_provider_credentials") == 1
    ciphertext = await scalar(app, "SELECT ciphertext FROM user_provider_credentials")
    assert isinstance(ciphertext, bytes)
    assert app.state.cipher.decrypt(ciphertext) == replacement


async def test_delete_removes_credential(client: AsyncClient, app: FastAPI) -> None:
    await register_and_login(client)
    await _save(client, "gemini", GEMINI_KEY)
    assert (await client.delete("/api/credentials/gemini")).status_code == 204
    assert await scalar(app, "SELECT count(*) FROM user_provider_credentials") == 0
    assert (await client.delete("/api/credentials/gemini")).status_code == 404
    listed = {c["provider"]: c for c in (await client.get("/api/credentials")).json()}
    assert listed["gemini"]["configured"] is False


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/credentials"),
        ("PUT", "/api/credentials/groq"),
        ("DELETE", "/api/credentials/groq"),
    ],
)
async def test_credentials_require_authentication(
    client: AsyncClient, method: str, path: str
) -> None:
    r = await client.request(method, path, json={"api_key": GROQ_KEY} if method == "PUT" else None)
    assert r.status_code == 401


async def test_users_cannot_see_or_delete_each_others_credentials(app: FastAPI) -> None:
    async with make_client(app) as alice, make_client(app) as bob:
        await register_and_login(alice, "alice@example.com")
        await register_and_login(bob, "bob@example.com")
        await _save(alice, "groq", GROQ_KEY)

        bob_view = (await bob.get("/api/credentials")).json()
        assert all(c["configured"] is False for c in bob_view)
        assert (await bob.delete("/api/credentials/groq")).status_code == 404

        alice_view = {c["provider"]: c for c in (await alice.get("/api/credentials")).json()}
        assert alice_view["groq"]["configured"] is True


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
async def test_unknown_provider_is_rejected(client: AsyncClient, method: str) -> None:
    await register_and_login(client)
    r = await client.request(
        method, "/api/credentials/openai", json={"api_key": GROQ_KEY} if method == "PUT" else None
    )
    assert r.status_code == 422
    assert GROQ_KEY not in r.text


async def test_rejected_key_is_not_echoed_in_validation_error(client: AsyncClient) -> None:
    await register_and_login(client)
    bad_key = "gsk_contains whitespace_" + "x" * 20
    r = await client.put("/api/credentials/groq", json={"api_key": bad_key})
    assert r.status_code == 422
    assert bad_key not in r.text and "whitespace_xxxx" not in r.text


async def test_api_keys_never_reach_logs(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    # Log every SQL statement with its bound parameters: the most likely leak path.
    caplog.set_level(logging.INFO, logger="sqlalchemy.engine")
    await register_and_login(client)
    await _save(client, "groq", GROQ_KEY)
    await _save(client, "gemini", GEMINI_KEY)
    await client.get("/api/credentials")
    await client.put("/api/credentials/groq", json={"api_key": GROQ_KEY + " tail"})
    await client.delete("/api/credentials/gemini")
    assert caplog.records  # logging was actually captured
    assert GROQ_KEY not in caplog.text and GEMINI_KEY not in caplog.text


async def test_encryption_key_is_never_returned(client: AsyncClient, encryption_key: str) -> None:
    await register_and_login(client)
    responses = [
        await client.put("/api/credentials/groq", json={"api_key": GROQ_KEY}),
        await client.get("/api/credentials"),
        await client.get("/api/auth/me"),
        await client.get("/readyz"),
        await client.get("/openapi.json"),
    ]
    for r in responses:
        assert encryption_key not in r.text
