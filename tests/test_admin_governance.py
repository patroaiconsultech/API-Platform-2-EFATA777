def test_admin_requires_admin_role(client, member_headers):
    response = client.get("/api/admin/overview", headers=member_headers)
    assert response.status_code == 403

def test_admin_is_tenant_scoped(client, admin_headers):
    client.post("/api/threads", headers=admin_headers, json={"title":"Admin"})
    body = client.get("/api/admin/overview", headers=admin_headers).json()
    assert body["tenant_id"] == "tenant-a"
    assert body["stats"]["threads"] == 1

def test_governance_reports_no_external_writes(client, member_headers):
    body = client.get("/api/governance/status", headers=member_headers).json()
    assert body["repository_write_executed"] is False
    assert body["deploy_executed"] is False
    assert body["production_authorization"] is False
