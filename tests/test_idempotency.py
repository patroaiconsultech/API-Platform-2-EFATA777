import json


def create_thread(client, headers):
    return client.post(
        "/api/threads",
        headers=headers,
        json={"title": "Idempotency"},
    ).json()


def parse_events(text):
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


def test_retry_returns_same_success_without_duplicate_messages(
    client,
    member_headers,
):
    thread = create_thread(client, member_headers)
    payload = {
        "thread_id": thread["thread_id"],
        "content": "Executar uma vez",
        "requested_agent": "Orion",
        "request_id": "request-idempotent-success",
    }
    first = client.post("/api/chat", headers=member_headers, json=payload)
    second = client.post("/api/chat", headers=member_headers, json=payload)
    assert first.status_code == second.status_code == 200
    assert first.json()["message_id"] == second.json()["message_id"]
    assert first.json()["execution_id"] == second.json()["execution_id"]
    messages = client.get(
        f"/api/threads/{thread['thread_id']}/messages",
        headers=member_headers,
    ).json()
    assert [item["role"] for item in messages] == ["user", "assistant"]


def test_reused_request_id_with_different_payload_fails_closed(
    client,
    member_headers,
):
    thread = create_thread(client, member_headers)
    first = {
        "thread_id": thread["thread_id"],
        "content": "Primeiro conteúdo",
        "requested_agent": "Orion",
        "request_id": "request-reused",
    }
    second = {**first, "content": "Conteúdo diferente"}
    assert client.post(
        "/api/chat",
        headers=member_headers,
        json=first,
    ).status_code == 200
    response = client.post(
        "/api/chat",
        headers=member_headers,
        json=second,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_error_retry_returns_same_terminal_record(
    client,
    member_headers,
):
    thread = create_thread(client, member_headers)
    payload = {
        "thread_id": thread["thread_id"],
        "content": "Erro controlado",
        "requested_agent": "Orion",
        "request_id": "request-idempotent-error",
        "simulate_error": True,
    }
    first = client.post("/api/chat", headers=member_headers, json=payload)
    second = client.post("/api/chat", headers=member_headers, json=payload)
    assert first.json()["status"] == second.json()["status"] == "error"
    assert first.json()["message_id"] == second.json()["message_id"]
    assert first.json()["error"]["code"] == "SIMULATED_CHAT_FAILURE"
    messages = client.get(
        f"/api/threads/{thread['thread_id']}/messages",
        headers=member_headers,
    ).json()
    assert [item["role"] for item in messages] == ["user", "assistant"]
    assert messages[-1]["status"] == "error"
    assert messages[-1]["error_code"] == "SIMULATED_CHAT_FAILURE"


def test_sse_retry_is_replayed_without_duplicate_messages(
    client,
    member_headers,
):
    thread = create_thread(client, member_headers)
    payload = {
        "thread_id": thread["thread_id"],
        "content": "Stream uma vez",
        "requested_agent": "Orion",
        "request_id": "request-stream-retry",
    }
    first = client.post(
        "/api/chat/stream",
        headers=member_headers,
        json=payload,
    )
    second = client.post(
        "/api/chat/stream",
        headers=member_headers,
        json=payload,
    )
    first_events = parse_events(first.text)
    second_events = parse_events(second.text)
    assert [event["event"] for event in first_events][-2:] == [
        "agent_done",
        "done",
    ]
    assert [event["event"] for event in second_events][-2:] == [
        "agent_done",
        "done",
    ]
    assert second_events[-1]["data"]["payload"]["replayed"] is True
    messages = client.get(
        f"/api/threads/{thread['thread_id']}/messages",
        headers=member_headers,
    ).json()
    assert len(messages) == 2
