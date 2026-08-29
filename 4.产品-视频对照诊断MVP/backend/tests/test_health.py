from fastapi.testclient import TestClient

from yongge_online.main import create_app


def test_health_reports_service_identity() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "yongge-online-api",
    }


