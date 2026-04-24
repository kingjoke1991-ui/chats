from app.schemas.common import HealthResponse


def test_health_schema() -> None:
    response = HealthResponse(status="ok")
    assert response.status == "ok"
