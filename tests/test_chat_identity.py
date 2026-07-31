from orkio_platform.domain.models import ResponseEnvelope


def setup_thread(client, headers):
    return client.post(
        "/api/threads",
        headers=headers,
        json={"title": "Chat"},
    ).json()


def test_explicit_agent_owns_response(client, member_headers):
    thread = setup_thread(client, member_headers)
    response = client.post(
        "/api/chat",
        headers=member_headers,
        json={
            "thread_id": thread["thread_id"],
            "content": "Arquitetura",
            "requested_agent": "Orion",
            "request_id": "request-fixed",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == "request-fixed"
    assert body["agent_id"] == body["agent_name"] == "Orion"
    assert body["final_speaker"] == body["turn_owner"] == "Orion"


def test_display_alias_does_not_change_canonical_ownership():
    envelope = ResponseEnvelope(
        message_id="message-1",
        request_id="request-1",
        execution_id="execution-1",
        thread_id="thread-1",
        tenant_id="tenant-a",
        agent_id="Orion",
        agent_name="Orion",
        display_name="Atlas",
        final_speaker="Orion",
        turn_owner="Orion",
        route_family="explicit_agent",
        content="ok",
        status="success",
    )
    assert envelope.display_name == "Atlas"
    assert envelope.turn_owner == "Orion"


def test_unknown_agent_fails_closed(client, member_headers):
    thread = setup_thread(client, member_headers)
    response = client.post(
        "/api/chat",
        headers=member_headers,
        json={
            "thread_id": thread["thread_id"],
            "content": "Teste",
            "requested_agent": "Unknown",
        },
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "AGENT_NOT_FOUND"
