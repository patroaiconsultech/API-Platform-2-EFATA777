def create_thread(client, headers, title="Alpha"):
    response = client.post(
        "/api/threads",
        headers=headers,
        json={"title": title},
    )
    assert response.status_code == 200
    return response.json()


def test_thread_visible_in_same_tenant(client, member_headers):
    thread = create_thread(client, member_headers)
    response = client.get("/api/threads", headers=member_headers)
    assert [item["thread_id"] for item in response.json()] == [
        thread["thread_id"]
    ]


def test_cross_tenant_and_unknown_thread_have_identical_404(
    client,
    member_headers,
):
    thread = create_thread(client, member_headers)
    other = {
        "X-Tenant-ID": "tenant-b",
        "X-User-ID": "user-b",
        "X-Role": "member",
    }
    cross_tenant = client.get(
        f"/api/threads/{thread['thread_id']}/messages",
        headers=other,
    )
    unknown = client.get(
        "/api/threads/thread-does-not-exist/messages",
        headers=other,
    )
    assert cross_tenant.status_code == unknown.status_code == 404
    assert cross_tenant.json() == unknown.json()
    assert cross_tenant.json()["error"] == {
        "code": "THREAD_NOT_FOUND",
        "message": "Thread not found.",
    }
