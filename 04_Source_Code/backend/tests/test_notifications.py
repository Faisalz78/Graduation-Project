from test_workflow import act, ready

from conftest import login


def inbox(client, unread_only=False):
    suffix = "?unread_only=true" if unread_only else ""
    response = client.get(f"/api/v1/notifications{suffix}")
    assert response.status_code == 200, response.text
    return response.json()


def test_workflow_notifications_reach_only_the_next_reviewers_and_owner(client, world):
    invoice = ready(client, world)
    submitted = act(client, invoice).json()

    login(client, world, "manager")
    manager_inbox = inbox(client)
    assert manager_inbox["unread_count"] == manager_inbox["total"] == 1
    assert manager_inbox["items"][0]["kind"] == "PROJECT_REVIEW_REQUIRED"
    assert manager_inbox["items"][0]["invoice_id"] == invoice["id"]
    assert "أولوية المراجعة" in manager_inbox["items"][0]["message"]

    login(client, world, "manager_b")
    assert inbox(client)["total"] == 0
    login(client, world, "finance")
    assert inbox(client)["total"] == 0
    login(client, world, "outsider")
    assert inbox(client)["total"] == 0

    login(client, world, "manager")
    finance_review = act(client, submitted, "APPROVE").json()
    login(client, world, "finance")
    assert inbox(client)["items"][0]["kind"] == "FINANCE_REVIEW_REQUIRED"
    login(client, world, "finance_peer")
    assert inbox(client)["items"][0]["kind"] == "FINANCE_REVIEW_REQUIRED"
    login(client, world)
    assert inbox(client)["items"][0]["kind"] == "PROJECT_APPROVED"

    login(client, world, "finance")
    approved = act(client, finance_review, "APPROVE").json()
    assert approved["status"] == "APPROVED"
    login(client, world)
    owner_inbox = inbox(client)
    assert owner_inbox["unread_count"] == 2
    assert owner_inbox["items"][0]["kind"] == "FINANCE_APPROVED"


def test_notification_read_state_csrf_scope_and_stale_transition_deduplication(client, world):
    invoice = ready(client, world)
    submitted = act(client, invoice).json()
    assert act(client, invoice).status_code == 409
    login(client, world, "manager")
    notifications = inbox(client, unread_only=True)
    assert notifications["total"] == notifications["unread_count"] == 1
    notification = notifications["items"][0]

    rejected = client.post(
        f"/api/v1/notifications/{notification['id']}/read",
        headers={"X-CSRF-Token": "invalid"},
    )
    assert rejected.status_code == 403
    assert inbox(client)["unread_count"] == 1

    login(client, world, "manager_b")
    assert client.post(f"/api/v1/notifications/{notification['id']}/read").status_code == 404
    login(client, world, "manager")
    marked = client.post(f"/api/v1/notifications/{notification['id']}/read")
    assert marked.status_code == 200
    assert marked.json()["read_at"] is not None
    assert inbox(client)["unread_count"] == 0
    assert client.post("/api/v1/notifications/read-all").json() == {"updated": 0}

    returned = act(client, submitted, "REQUEST_CHANGES", comment="صحح الكمية").json()
    assert returned["status"] == "CHANGES_REQUESTED"
    login(client, world)
    assert inbox(client)["items"][0]["kind"] == "CHANGES_REQUESTED"
