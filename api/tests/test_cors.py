from fastapi.testclient import TestClient

ACAO = "access-control-allow-origin"
ALLOWED_ORIGIN = "http://allowed.test"  # matches the settings fixture
UNKNOWN_ORIGIN = "http://evil.test"


def test_cors_allowed_origin_gets_headers(client: TestClient) -> None:
    simple = client.get("/health", headers={"Origin": ALLOWED_ORIGIN})
    preflight = client.options(
        "/health",
        headers={"Origin": ALLOWED_ORIGIN, "Access-Control-Request-Method": "GET"},
    )

    assert simple.headers.get(ACAO) == ALLOWED_ORIGIN
    assert preflight.status_code == 200
    assert preflight.headers.get(ACAO) == ALLOWED_ORIGIN


def test_cors_unknown_origin_gets_none(client: TestClient) -> None:
    simple = client.get("/health", headers={"Origin": UNKNOWN_ORIGIN})
    preflight = client.options(
        "/health",
        headers={"Origin": UNKNOWN_ORIGIN, "Access-Control-Request-Method": "GET"},
    )

    assert ACAO not in simple.headers
    assert ACAO not in preflight.headers
