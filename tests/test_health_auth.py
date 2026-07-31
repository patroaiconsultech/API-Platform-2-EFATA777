def test_health_is_public(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_readiness_reports_memory_fallback(client):
    body = client.get("/api/readiness").json()
    assert body["database"] == "memory"
    assert body["persistent_repository"] is False
    assert body["production_ready"] is False

def test_protected_route_requires_context(client):
    response = client.get("/api/agents")
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "AUTH_CONTEXT_REQUIRED"
