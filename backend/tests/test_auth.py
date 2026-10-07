import pytest
from argon2 import PasswordHasher
from fastapi import FastAPI
from httpx2 import AsyncClient

from tests.conftest import (
    FRONTEND_ORIGIN,
    PASSWORD,
    execute,
    make_client,
    register_and_login,
    scalar,
)

pytestmark = pytest.mark.anyio

COOKIE = "rp_session"


# ---- registration ----


async def test_register_creates_user_with_normalised_email(client: AsyncClient) -> None:
    r = await client.post(
        "/api/auth/register", json={"email": "  Alice@Example.COM ", "password": PASSWORD}
    )
    assert r.status_code == 201
    body = r.json()
    assert set(body) == {"id", "email", "created_at"}
    assert body["email"] == "alice@example.com"
    assert PASSWORD not in r.text


async def test_register_rejects_duplicate_email_case_insensitively(client: AsyncClient) -> None:
    payload = {"email": "bob@example.com", "password": PASSWORD}
    assert (await client.post("/api/auth/register", json=payload)).status_code == 201
    payload["email"] = "BOB@example.com"
    r = await client.post("/api/auth/register", json=payload)
    assert r.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "password": PASSWORD},
        {"email": "carol@example.com", "password": "Qz7!pw"},
        {"email": "carol@example.com", "password": "x" * 129},
        {"email": "carol@example.com"},
    ],
)
async def test_register_rejects_invalid_input_without_echoing_it(
    client: AsyncClient, payload: dict[str, str]
) -> None:
    r = await client.post("/api/auth/register", json=payload)
    assert r.status_code == 422
    if "password" in payload:
        assert payload["password"] not in r.text


async def test_password_is_stored_as_argon2id_hash(client: AsyncClient, app: FastAPI) -> None:
    await client.post("/api/auth/register", json={"email": "dan@example.com", "password": PASSWORD})
    stored = await scalar(app, "SELECT password_hash FROM users WHERE email = 'dan@example.com'")
    assert isinstance(stored, str)
    assert stored.startswith("$argon2id$")
    assert PASSWORD not in stored
    assert PasswordHasher().verify(stored, PASSWORD)


# ---- login ----


async def test_login_sets_secure_httponly_session_cookie(client: AsyncClient, app: FastAPI) -> None:
    await client.post("/api/auth/register", json={"email": "eve@example.com", "password": PASSWORD})
    r = await client.post(
        "/api/auth/login", json={"email": "EVE@example.com", "password": PASSWORD}
    )
    assert r.status_code == 200
    assert r.json()["email"] == "eve@example.com"

    set_cookie = r.headers["set-cookie"]
    for attribute in ("HttpOnly", "Secure", "SameSite=lax", "Path=/", "Max-Age=604800"):
        assert attribute in set_cookie
    token = client.cookies[COOKIE]
    assert len(token) >= 43  # 32 random bytes, url-safe base64
    assert token not in r.text  # never in the JSON body

    # Only a digest of the token is stored.
    assert await scalar(app, "SELECT count(*) FROM sessions") == 1
    assert await scalar(app, "SELECT count(*) FROM sessions WHERE token_hash = :t", t=token) == 0


async def test_wrong_password_and_unknown_account_are_indistinguishable(
    client: AsyncClient,
) -> None:
    await client.post("/api/auth/register", json={"email": "fay@example.com", "password": PASSWORD})
    wrong = await client.post(
        "/api/auth/login", json={"email": "fay@example.com", "password": "wrong password!"}
    )
    unknown = await client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert COOKIE not in client.cookies


async def test_cross_origin_state_change_is_rejected(client: AsyncClient) -> None:
    payload = {"email": "gil@example.com", "password": PASSWORD}
    evil = await client.post(
        "/api/auth/register", json=payload, headers={"Origin": "https://evil.example"}
    )
    ok = await client.post("/api/auth/register", json=payload, headers={"Origin": FRONTEND_ORIGIN})
    assert evil.status_code == 403
    assert ok.status_code == 201


# ---- sessions ----


async def test_me_with_valid_session(client: AsyncClient) -> None:
    await register_and_login(client)
    r = await client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == "alice@example.com"
    assert "password" not in r.text and "hash" not in r.text


async def test_me_without_session(client: AsyncClient) -> None:
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_me_with_invalid_session(app: FastAPI) -> None:
    async with make_client(app) as client:
        client.cookies.set(COOKIE, "forged-token-value")
        assert (await client.get("/api/auth/me")).status_code == 401


async def test_me_with_expired_session(client: AsyncClient, app: FastAPI) -> None:
    await register_and_login(client)
    await execute(app, "UPDATE sessions SET expires_at = now() - interval '1 second'")
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_logout_revokes_session_server_side(client: AsyncClient, app: FastAPI) -> None:
    await register_and_login(client)
    token = client.cookies[COOKIE]

    r = await client.post("/api/auth/logout")
    assert r.status_code == 204
    assert COOKIE not in client.cookies  # cookie cleared
    assert await scalar(app, "SELECT count(*) FROM sessions WHERE revoked_at IS NOT NULL") == 1

    # Replaying the old token must fail even though the browser no longer holds it.
    async with make_client(app) as replay:
        replay.cookies.set(COOKIE, token)
        assert (await replay.get("/api/auth/me")).status_code == 401


async def test_session_expiry_slides_when_past_half_ttl(client: AsyncClient, app: FastAPI) -> None:
    await register_and_login(client)
    await execute(app, "UPDATE sessions SET expires_at = now() + interval '1 day'")
    r = await client.get("/api/auth/me")
    assert r.status_code == 200
    assert "Max-Age=604800" in r.headers["set-cookie"]
    remaining = await scalar(
        app, "SELECT extract(epoch FROM expires_at - now()) / 86400 FROM sessions"
    )
    assert remaining is not None and float(str(remaining)) > 6.9
