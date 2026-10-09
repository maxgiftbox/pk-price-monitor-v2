from fastapi.testclient import TestClient

from src.main import app


def test_pricing_cors_preflight_is_not_blocked_by_auth():
    response = TestClient(app).options(
        "/api/pricing/dashboard",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
