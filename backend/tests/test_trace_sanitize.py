import uuid

import pytest

from app.services.trace_sanitize import REDACTED, redact_text, sanitize
from tests.llm_fakes import GEMINI_TEST_KEY, GROQ_TEST_KEY


@pytest.mark.parametrize(
    "secret",
    [
        GROQ_TEST_KEY,
        GEMINI_TEST_KEY,
        "Bearer abcdefgh12345678",
        "gAAAAABpZx1t2qY3kL9mN0pQ4rS5tU6vW7xY8zA",  # Fernet token
        "$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA",
        "Kp3vQ9xZ2mL7nR4tW8yB1cF6hJ0sD5gA-_eUiOq",  # opaque session-style token
    ],
)
def test_credential_shaped_strings_are_redacted(secret: str) -> None:
    out = redact_text(f"value: {secret} end")
    assert secret not in out and REDACTED in out


def test_database_url_password_is_redacted_but_host_kept() -> None:
    out = redact_text("postgresql+asyncpg://rp:hunter2pass@db.example:5432/app")
    assert "hunter2pass" not in out and "db.example" in out and "rp:" in out


@pytest.mark.parametrize(
    ("url", "secret"),
    [
        ("https://api.openalex.org/works?search=sleep&api_key=oa-TESTONLY-key-0000", "oa-TESTONLY"),
        (
            "https://cdn.example/a.pdf?X-Amz-Signature=abc123def&X-Amz-Credential=AKIDTEST",
            "abc123def",
        ),
        ("https://repo.example/a.pdf?token=short-tok&page=2", "short-tok"),
    ],
)
def test_query_string_credentials_are_redacted(url: str, secret: str) -> None:
    out = redact_text(url)
    assert secret not in out and REDACTED in out
    assert out.startswith(url.split("?")[0])  # host and path stay useful for debugging


def test_semantic_scholar_header_name_is_sensitive() -> None:
    assert sanitize({"x-api-key": "s2-TESTONLY-key-0000"}) == {"x-api-key": REDACTED}


@pytest.mark.parametrize(
    "safe",
    [
        str(uuid.uuid4()),
        "649def34f8be52c8b66281af98ae884c09aef38b",  # Semantic Scholar id (hex)
        "10.1016/j.neuron.2020.01.001",
        "pneumonoultramicroscopicsilicovolcanoconiosis",  # long word, no digits
        "Sleep deprivation reduced recall by 20% in adults.",
    ],
)
def test_research_content_is_preserved(safe: str) -> None:
    assert redact_text(safe) == safe


def test_sensitive_keys_are_redacted_recursively() -> None:
    data = {
        "query": "sleep",
        "headers": {"Authorization": "x", "Cookie": "y", "Accept": "json"},
        "api_key": "plain",
        "password": "p",
        "session_token": "t",
        "nested": [{"x-goog-api-key": "k", "tokens_in": 12}],
    }
    out = sanitize(data)
    assert out["query"] == "sleep"
    assert out["headers"] == {"Authorization": REDACTED, "Cookie": REDACTED, "Accept": "json"}
    assert out["api_key"] == out["password"] == out["session_token"] == REDACTED
    assert out["nested"] == [{"x-goog-api-key": REDACTED, "tokens_in": 12}]


def test_sanitize_bounds_size_and_depth() -> None:
    deep: dict[str, object] = {}
    cursor = deep
    for _ in range(20):
        cursor["d"] = {}
        cursor = cursor["d"]  # type: ignore[assignment]
    out = sanitize({"deep": deep, "long": "z" * 5000, "many": list(range(500))})
    assert len(out["long"]) == 1000
    assert len(out["many"]) == 50
    assert "[TRUNCATED]" in str(out["deep"])
