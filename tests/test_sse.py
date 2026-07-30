def setup_thread(client, headers):
    return client.post(
        "/api/threads",
        headers=headers,
        json={"title": "SSE"},
    ).json()


def parse_events(text):
    events = []
    current = {}
    for line in text.splitlines():
        if line.startswith("id: "):
            current["id"] = line[4:]
        elif line.startswith("event: "):
            current["event"] = line[7:]
        elif line.startswith("data: "):
            current["data"] = line[6:]
        elif line == "" and current:
            events.append(current)
            current = {}
    if current:
        events.append(current)
    return events


def test_success_stream_ends_agent_done_done(client, member_headers):
    thread = setup_thread(client, member_headers)
    response = client.post(
        "/api/chat/stream",
        headers=member_headers,
        json={
            "thread_id": thread["thread_id"],
            "content": "SSE",
            "requested_agent": "Orion",
        },
    )
    assert response.status_code == 200
    events = parse_events(response.text)
    assert [event["event"] for event in events][-2:] == ["agent_done", "done"]


def test_error_stream_ends_error_done(client, member_headers):
    thread = setup_thread(client, member_headers)
    response = client.post(
        "/api/chat/stream",
        headers=member_headers,
        json={
            "thread_id": thread["thread_id"],
            "content": "SSE",
            "requested_agent": "Orion",
            "simulate_error": True,
        },
    )
    assert response.status_code == 200
    events = parse_events(response.text)
    assert [event["event"] for event in events][-2:] == ["error", "done"]


def test_stream_identity_is_canonical(client, member_headers):
    thread = setup_thread(client, member_headers)
    response = client.post(
        "/api/chat/stream",
        headers=member_headers,
        json={
            "thread_id": thread["thread_id"],
            "content": "SSE",
            "requested_agent": "Orion",
        },
    )
    import json
    for event in parse_events(response.text):
        data = json.loads(event["data"])
        assert data["tenant_id"] == "tenant-a"
        assert data["agent_id"] == "Orion"
        assert data["turn_owner"] == "Orion"
