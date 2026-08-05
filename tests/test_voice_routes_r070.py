
def test_voice_endpoint_fails_closed_when_feature_disabled(
    client,
    member_headers,
):
    thread = client.post(
        "/api/threads",
        headers=member_headers,
        json={"title": "Voice disabled"},
    ).json()
    response = client.post(
        "/api/voice/sessions",
        headers=member_headers,
        json={
            "thread_id": thread["thread_id"],
            "requested_agent": "Orkio",
            "interaction_mode": "single",
            "consent_granted": True,
        },
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "REALTIME_VOICE_DISABLED"
