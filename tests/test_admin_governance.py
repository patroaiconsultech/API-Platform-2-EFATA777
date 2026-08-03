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


def test_auth_status_exposes_only_configured_demo_admin_profile(client):
    body = client.get("/api/auth/status").json()
    assert body["demo_admin_enabled"] is True
    assert body["demo_admin_profile"] == {
        "tenant_id": "tenant-a",
        "user_id": "admin-a",
        "role": "admin",
    }


def test_evolution_proposal_requires_admin_before_feature_gate(
    client,
    member_headers,
):
    response = client.post(
        "/api/governance/evolution/proposals",
        headers=member_headers,
        json={
            "objective": "Improve UX",
            "evidence": [],
            "constraints": ["proposal_only"],
        },
    )
    assert response.status_code == 403
    body = response.json()
    detail = body.get("error") or body.get("detail")
    assert detail["code"] == "ADMIN_ROLE_REQUIRED"


def test_admin_overview_exposes_truthful_audit_snapshot(
    client,
    admin_headers,
):
    client.post(
        "/api/threads",
        headers=admin_headers,
        json={"title": "Audit snapshot"},
    )
    response = client.get(
        "/api/admin/overview",
        headers=admin_headers,
    )
    assert response.status_code == 200
    body = response.json()

    assert body["scope"] == "tenant_only"
    assert body["runtime"]["release_version"] == "0.6.2"
    assert body["runtime"]["execution_graph"] == "trace_lite"
    assert body["runtime"]["voice_webrtc"] == "planned"
    assert body["capability_summary"]["available"] >= 4
    assert body["capability_summary"]["planned"] >= 5
    assert body["governance"] == {
        "proposal_only": False,
        "write_executed": False,
        "commit_executed": False,
        "merge_executed": False,
        "deploy_executed": False,
        "migration_executed": False,
        "human_approval_required": True,
    }
