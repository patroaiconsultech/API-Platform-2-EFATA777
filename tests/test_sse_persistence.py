import json


def thread(client, headers):
    return client.post(
        "/api/threads",
        headers=headers,
        json={"title": "SSE"},
    ).json()


def events(text):
    result = []
    current = {}
    for line in text.splitlines():
        if line.startswith("event: "):
            current["event"] = line[7:]
        elif line.startswith("data: "):
            current["data"] = json.loads(line[6:])
        elif line == "" and current:
            result.append(current)
            current = {}
    return result


def test_stream_persists_exactly_one_atomic_turn(client, member_headers):
    created = thread(client, member_headers)
    response = client.post(
        "/api/chat/stream",
        headers=member_headers,
        json={
            "thread_id": created["thread_id"],
            "content": "Persistir uma vez",
            "requested_agent": "Orion",
            "request_id": "request-fixed",
        },
    )
    observed = events(response.text)
    assert [item["event"] for item in observed][-2:] == [
        "agent_done",
        "done",
    ]
    message = observed[-2]["data"]["payload"]["message"]
    assert message["request_id"] == "request-fixed"
    messages = client.get(
        f"/api/threads/{created['thread_id']}/messages",
        headers=member_headers,
    ).json()
    assert [item["role"] for item in messages] == ["user", "assistant"]
    assert messages[-1]["message_id"] == message["message_id"]
    assert messages[-1]["agent_id"] == messages[-1]["turn_owner"] == "Orion"


def test_error_stream_persists_terminal_error_and_ends(client, member_headers):
    created = thread(client, member_headers)
    response = client.post(
        "/api/chat/stream",
        headers=member_headers,
        json={
            "thread_id": created["thread_id"],
            "content": "Erro",
            "requested_agent": "Orion",
            "request_id": "request-error",
            "simulate_error": True,
        },
    )
    observed = events(response.text)
    assert [item["event"] for item in observed][-2:] == ["error", "done"]
    assert observed[-2]["data"]["payload"]["code"] == (
        "SIMULATED_CHAT_FAILURE"
    )
    messages = client.get(
        f"/api/threads/{created['thread_id']}/messages",
        headers=member_headers,
    ).json()
    assert [item["role"] for item in messages] == ["user", "assistant"]
    assert messages[-1]["status"] == "error"
    assert messages[-1]["error_code"] == "SIMULATED_CHAT_FAILURE"
