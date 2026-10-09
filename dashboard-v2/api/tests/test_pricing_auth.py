from fastapi.testclient import TestClient

from src.main import app


def test_pricing_api_rejects_anonymous_requests():
    response = TestClient(app).get("/api/pricing/filters")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "PRICING_AUTH_REQUIRED"


def test_login_rejects_wrong_password():
    response = TestClient(app).post(
        "/api/pricing/auth", json={"password": "wrong-password"}
    )
    assert response.status_code == 401


def test_login_issues_a_valid_session_token():
    client = TestClient(app)
    login = client.post(
        "/api/pricing/auth", json={"password": "test-password"}
    )
    assert login.status_code == 200
    token = login.json()["token"]
    status = client.get(
        "/api/pricing/auth", headers={"Authorization": f"Bearer {token}"}
    )
    assert status.json() == {"authenticated": True}
