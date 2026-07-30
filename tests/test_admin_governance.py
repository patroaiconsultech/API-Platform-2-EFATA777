def test_admin_requires_admin_role(client, member_headers):
    response = client.get("/api/admin/overview", headers=member_headers)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ADMIN_ROLE_REQUIRED"


def test_admin_is_tenant_scoped(client, admin_headers):
    client.post("/api/threads", headers=admin_headers, json={"title": "Admin"})
    response = client.get("/api/admin/overview", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["tenant_id"] == "tenant-a"
    assert response.json()["stats"]["threads"] == 1


def test_governance_reports_no_external_writes(client, member_headers):
    response = client.get("/api/governance/status", headers=member_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["repository_write_executed"] is False
    assert body["deploy_executed"] is False
    assert body["production_authorization"] is False
