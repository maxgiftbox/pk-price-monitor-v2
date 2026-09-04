from fastapi.testclient import TestClient
from src.main import app

def test_health_never_reads_repository():
    app.state.repository=type("Repo",(),{"get":lambda self: (_ for _ in ()).throw(AssertionError("refresh"))})()
    assert TestClient(app).get("/api/health").status_code == 200
