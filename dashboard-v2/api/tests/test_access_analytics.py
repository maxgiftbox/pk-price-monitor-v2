from fastapi.testclient import TestClient

from src.main import app


class RecordingWriter:
    def __init__(self):
        self.events = []

    def record(self, event):
        self.events.append(event)


def test_records_dashboard_access_with_forwarded_ip():
    writer = RecordingWriter()
    original = app.state.access_analytics_writer
    app.state.access_analytics_writer = writer
    try:
        response = TestClient(app).post(
            "/api/analytics/access",
            headers={"X-Forwarded-For": "203.0.113.10, 10.0.0.2"},
            json={
                "sessionId": "7c15ec3a-7ab9-4f15-8a6c-aaf430b9a5a9",
                "eventType": "session_start",
                "path": "/social-intelligence",
            },
        )
    finally:
        app.state.access_analytics_writer = original

    assert response.status_code == 202
    assert response.json() == {"accepted": True}
    assert len(writer.events) == 1
    assert writer.events[0].ip_address == "203.0.113.10"
    assert writer.events[0].path == "/social-intelligence"


def test_rejects_invalid_dashboard_path():
    response = TestClient(app).post(
        "/api/analytics/access",
        json={
            "sessionId": "7c15ec3a-7ab9-4f15-8a6c-aaf430b9a5a9",
            "eventType": "page_view",
            "path": "https://example.com/not-a-dashboard-path",
        },
    )
    assert response.status_code == 422
