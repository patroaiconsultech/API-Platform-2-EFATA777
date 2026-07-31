import json


def parse_events(text: str) -> list[dict]:
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


def test_unknown_thread_stream_ends_error_done(client, member_headers):
    response = client.post(
        "/api/chat/stream",
        headers=member_headers,
        json={
            "thread_id": "thread-does-not-exist",
            "content": "Teste pré-contexto",
            "requested_agent": "Orion",
            "request_id": "request-unknown-thread",
        },
    )
    assert response.status_code == 200
    observed = parse_events(response.text)
    assert [item["event"] for item in observed] == ["error", "done"]
    assert observed[0]["data"]["payload"]["code"] == "THREAD_NOT_FOUND"
    assert observed[1]["data"]["payload"]["error_code"] == "THREAD_NOT_FOUND"
    assert observed[0]["data"]["execution_id"] is None
    assert observed[0]["data"]["context_status"] == "NOT_RESOLVED"


def test_invalid_agent_stream_ends_error_done(client, member_headers):
    thread = client.post(
        "/api/threads",
        headers=member_headers,
        json={"title": "Invalid agent"},
    ).json()
    response = client.post(
        "/api/chat/stream",
        headers=member_headers,
        json={
            "thread_id": thread["thread_id"],
            "content": "Teste de agente inválido",
            "requested_agent": "Unknown",
            "request_id": "request-invalid-agent",
        },
    )
    assert response.status_code == 200
    observed = parse_events(response.text)
    assert [item["event"] for item in observed] == ["error", "done"]
    assert observed[0]["data"]["payload"]["code"] == "AGENT_NOT_FOUND"
    assert observed[1]["data"]["payload"]["error_code"] == "AGENT_NOT_FOUND"
    assert observed[0]["data"]["execution_id"] is None
    assert observed[0]["data"]["agent_id"] == "Unknown"
