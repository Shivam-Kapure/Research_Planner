from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _client(frontend_origin: str = "http://localhost:3000") -> TestClient:
    return TestClient(create_app(Settings(environment="test", frontend_origin=frontend_origin)))


def test_healthz_returns_ok() -> None:
    response = _client().get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_reports_ready_with_checks() -> None:
    response = _client().get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert isinstance(body["checks"], dict)


def test_cors_allows_only_configured_frontend_origin() -> None:
    client = _client("https://researchpilot.example")
    allowed = client.get("/healthz", headers={"Origin": "https://researchpilot.example"})
    denied = client.get("/healthz", headers={"Origin": "https://evil.example"})
    assert allowed.headers.get("access-control-allow-origin") == "https://researchpilot.example"
    assert "access-control-allow-origin" not in denied.headers
