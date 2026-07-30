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
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["agent_id"] == "Orion"
    assert body["agent_name"] == "Orion"
    assert body["display_name"] == "Orion"
    assert body["final_speaker"] == "Orion"
    assert body["turn_owner"] == "Orion"
    assert body["tenant_id"] == "tenant-a"


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


def test_messages_persist_with_same_identity(client, member_headers):
    thread = setup_thread(client, member_headers)
    client.post(
        "/api/chat",
        headers=member_headers,
        json={
            "thread_id": thread["thread_id"],
            "content": "Teste",
            "requested_agent": "Orion",
        },
    )
    response = client.get(
        f"/api/threads/{thread['thread_id']}/messages",
        headers=member_headers,
    )
    messages = response.json()
    assistant = messages[-1]
    assert assistant["role"] == "assistant"
    assert assistant["agent_id"] == assistant["turn_owner"] == "Orion"
