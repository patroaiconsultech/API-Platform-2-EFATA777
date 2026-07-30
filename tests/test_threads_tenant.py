def create_thread(client, headers, title="Alpha"):
    response = client.post("/api/threads", headers=headers, json={"title": title})
    assert response.status_code == 200
    return response.json()


def test_thread_visible_in_same_tenant(client, member_headers):
    thread = create_thread(client, member_headers)
    response = client.get("/api/threads", headers=member_headers)
    assert response.status_code == 200
    assert [item["thread_id"] for item in response.json()] == [thread["thread_id"]]


def test_thread_not_visible_cross_tenant(client, member_headers):
    thread = create_thread(client, member_headers)
    other = {
        "X-Tenant-ID": "tenant-b",
        "X-User-ID": "user-b",
        "X-Role": "member",
    }
    response = client.get("/api/threads", headers=other)
    assert response.status_code == 200
    assert response.json() == []

    messages = client.get(
        f"/api/threads/{thread['thread_id']}/messages",
        headers=other,
    )
    assert messages.status_code == 404
    assert messages.json()["error"]["code"] == "THREAD_NOT_FOUND"
