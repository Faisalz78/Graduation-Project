from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_invoice_data import draft, item, payload, save

from app.core.config import get_settings
from app.main import app
from app.models import Attachment, Invoice, Project, ProjectMember, User
from conftest import login


def ready(client, world):
    invoice = draft(client, world)
    supplier = client.post("/api/v1/suppliers", json={"name": "Workflow test supplier"}).json()
    result = save(client, invoice, payload(invoice, supplier_id=supplier["id"]))
    assert result.status_code == 200, result.text
    return result.json()


def act(client, invoice, action="SUBMIT", **changes):
    return client.post(
        f"/api/v1/invoices/{invoice['id']}/workflow",
        json={
            "revision": invoice["revision"],
            "action": action,
            "confirmed": True,
            **changes,
        },
    )


def current(client, invoice):
    response = client.get(f"/api/v1/invoices/{invoice['id']}")
    assert response.status_code == 200, response.text
    return response.json()


def test_complete_review_scopes_snapshots_and_original(client, world):
    invoice = ready(client, world)
    original = client.get(invoice["attachment"]["url"]).content
    assert invoice["workflow"]["missing_fields"] == []
    for actor in ("manager", "finance"):
        login(client, world, actor)
        assert client.get(f"/api/v1/invoices/{invoice['id']}").status_code == 404
        assert client.get(invoice["attachment"]["url"]).status_code == 404
        assert client.get("/api/v1/invoices").json()["total"] == 0
    login(client, world)
    submitted = act(client, invoice).json()
    assert submitted["status"] == "PROJECT_REVIEW"
    assert submitted["revision"] == submitted["workflow"]["submitted_revision"] == 3
    event = submitted["events"][-1]
    assert event["details"]["employee_confirmed"] is True
    assert event["details"]["snapshot"]["totals"]["grand_total"] == "218.50"
    assert event["details"]["audit_snapshot"]["summary"] == "INCOMPLETE"
    assert submitted["workflow"]["allowed_actions"] == []
    assert save(client, submitted, payload(submitted)).status_code == 409
    for actor in ("peer", "manager_b", "outsider"):
        login(client, world, actor)
        assert client.get(f"/api/v1/invoices/{invoice['id']}").status_code == 404
        assert client.get(invoice["attachment"]["url"]).status_code == 404
        assert act(client, submitted, "APPROVE").status_code == 404
    login(client, world, "finance")
    assert current(client, invoice)["workflow"]["allowed_actions"] == []
    assert act(client, submitted, "APPROVE").status_code == 403
    login(client, world, "manager")
    assert client.get("/api/v1/invoices?status=PROJECT_REVIEW").json()["total"] == 1
    assert client.get("/api/v1/invoices?status=DRAFT").json()["total"] == 0
    assert client.get("/api/v1/invoices?status=UNKNOWN").status_code == 422
    assert client.get(invoice["attachment"]["url"]).content == original
    reviewed = act(client, submitted, "APPROVE", comment="Project reviewed").json()
    assert reviewed["status"] == "FINANCE_REVIEW" and reviewed["revision"] == 4
    assert reviewed["workflow"]["project_approved_revision"] == 3
    assert act(client, reviewed, "APPROVE").status_code == 403
    login(client, world, "finance")
    approved = act(client, reviewed, "APPROVE").json()
    assert approved["status"] == "APPROVED" and approved["revision"] == 5
    assert approved["workflow"]["allowed_actions"] == []
    for action in ("APPROVE", "REQUEST_CHANGES", "REJECT", "SUBMIT"):
        assert act(client, approved, action, comment="Terminal state").status_code == 403
    assert [e["action"] for e in approved["events"]][-3:] == [
        "INVOICE_SUBMITTED",
        "PROJECT_APPROVED",
        "FINANCE_APPROVED",
    ]
    assert all(e["details"]["submitted_revision"] == 3 for e in approved["events"][-3:])
    login(client, world)
    final = current(client, invoice)
    assert final["status"] == "APPROVED"
    assert client.get(invoice["attachment"]["url"]).content == original
    assert save(client, final, payload(final)).status_code == 409
    assert act(client, final).status_code == 403


@pytest.mark.parametrize("stage", ["manager", "finance"])
def test_changes_restart_project_review_and_invalidate_old_approvals(client, world, stage):
    invoice = ready(client, world)
    submitted = act(client, invoice).json()
    login(client, world, "manager")
    if stage == "finance":
        submitted = act(client, submitted, "APPROVE").json()
        login(client, world, "finance")
    returned = act(client, submitted, "REQUEST_CHANGES", comment="Correct quantity").json()
    assert returned["status"] == "CHANGES_REQUESTED"
    assert returned["workflow"]["project_approved_revision"] is None
    assert returned["events"][-1]["details"]["comment"] == "Correct quantity"
    assert returned["workflow"]["allowed_actions"] == []
    login(client, world)
    assert current(client, invoice)["workflow"]["allowed_actions"] == ["EDIT", "SUBMIT"]
    updated = save(
        client,
        returned,
        payload(returned, supplier_id=invoice["supplier"]["id"], items=[item(quantity="3")]),
    ).json()
    assert updated["status"] == "CHANGES_REQUESTED"
    assert updated["totals"]["grand_total"] == "333.50"
    resent = act(client, updated, comment="Quantity corrected").json()
    assert resent["status"] == "PROJECT_REVIEW"
    assert resent["workflow"]["submitted_revision"] == resent["revision"] > 3
    assert resent["events"][-1]["action"] == "INVOICE_RESUBMITTED"
    login(client, world, "finance")
    assert act(client, resent, "APPROVE").status_code == 403
    login(client, world, "manager")
    reviewed = act(client, resent, "APPROVE").json()
    login(client, world, "finance")
    assert act(client, reviewed, "APPROVE").json()["status"] == "APPROVED"


@pytest.mark.parametrize("stage", ["manager", "finance"])
def test_rejection_is_terminal_and_requires_reason(client, world, stage):
    invoice = act(client, ready(client, world)).json()
    login(client, world, "manager")
    if stage == "finance":
        invoice = act(client, invoice, "APPROVE").json()
        login(client, world, "finance")
    for comment in (None, "", "   "):
        assert act(client, invoice, "REJECT", comment=comment).status_code == 422
        assert act(client, invoice, "REQUEST_CHANGES", comment=comment).status_code == 422
    result = act(client, invoice, "REJECT", comment="Duplicate claim").json()
    assert result["status"] == "REJECTED"
    assert result["events"][-1]["details"]["comment"] == "Duplicate claim"
    for action in ("APPROVE", "REQUEST_CHANGES", "REJECT", "SUBMIT"):
        assert act(client, result, action, comment="Attempt").status_code == 403
    login(client, world)
    assert act(client, result).status_code == 403
    assert save(client, result, payload(result)).status_code == 409


@pytest.mark.parametrize(
    "field,value,label",
    [
        ("supplier_id", None, "المورد"),
        ("invoice_number", None, "رقم الفاتورة"),
        ("invoice_date", None, "تاريخ الفاتورة"),
        ("items", [], "بند واحد"),
    ],
)
def test_missing_submission_fields_do_not_change_state(client, world, field, value, label):
    invoice = ready(client, world)
    changes = {"supplier_id": invoice["supplier"]["id"], field: value}
    incomplete = save(client, invoice, payload(invoice, **changes)).json()
    response = act(client, incomplete)
    assert response.status_code == 422 and label in response.text
    assert current(client, incomplete) == incomplete


@pytest.mark.parametrize(
    "change",
    [
        {"confirmed": False},
        {"confirmed": "true"},
        {"revision": True},
        {"revision": 0},
        {"revision": "2"},
        {"action": "PAY"},
        {"comment": "a" * 2001},
        {"comment": "\x00"},
        {"role": "FINANCE_MANAGER"},
    ],
)
def test_invalid_action_payloads_are_atomic(client, world, change):
    invoice = ready(client, world)
    assert act(client, invoice, **change).status_code == 422
    assert current(client, invoice) == invoice


def test_submission_confirmation_csrf_and_repeated_request(client, world):
    invoice = ready(client, world)
    response = client.post(
        f"/api/v1/invoices/{invoice['id']}/workflow",
        json={"revision": invoice["revision"], "action": "SUBMIT"},
    )
    assert response.status_code == 422
    response = client.post(
        f"/api/v1/invoices/{invoice['id']}/workflow",
        json={"revision": invoice["revision"], "action": "SUBMIT", "confirmed": True},
        headers={"X-CSRF-Token": "bad"},
    )
    assert response.status_code == 403
    submitted = act(client, invoice).json()
    assert act(client, invoice).status_code == 409
    assert current(client, invoice) == submitted


def test_stale_decision_and_concurrent_review_have_one_winner(client, world):
    invoice = act(client, ready(client, world)).json()

    def decide(action):
        with TestClient(app) as browser:
            browser.headers["Origin"] = get_settings().app_origin
            login(browser, world, "manager")
            return act(browser, invoice, action, comment="Concurrent review").status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(decide, ["APPROVE", "REQUEST_CHANGES"])) == [200, 409]
    login(client, world, "manager")
    result = current(client, invoice)
    assert result["revision"] == invoice["revision"] + 1
    assert len(result["events"]) == len(invoice["events"]) + 1
    assert act(client, invoice, "REJECT", comment="Stale").status_code == 409


def test_edit_racing_submission_cannot_approve_unsent_data(client, world):
    invoice = ready(client, world)

    def request(action):
        with TestClient(app) as browser:
            browser.headers["Origin"] = get_settings().app_origin
            login(browser, world)
            if action == "submit":
                return act(browser, invoice).status_code
            return save(
                browser,
                invoice,
                payload(invoice, supplier_id=invoice["supplier"]["id"], invoice_number="Changed"),
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(request, ["submit", "edit"])) == [200, 409]
    result = current(client, invoice)
    assert result["revision"] == 3 and len(result["events"]) == 4
    if result["status"] == "PROJECT_REVIEW":
        assert result["invoice_number"] == invoice["invoice_number"]


@pytest.mark.parametrize("revocation", ["membership", "project", "company"])
def test_reviewer_access_revocation_is_effective_on_next_request(client, world, revocation):
    invoice = act(client, ready(client, world)).json()
    login(client, world, "manager")
    assert current(client, invoice)["status"] == "PROJECT_REVIEW"
    with Session(world["admin_engine"]) as db:
        if revocation == "membership":
            member = db.get(
                ProjectMember, (world["projects"]["a"].id, world["users"]["manager"].id)
            )
            member.membership_role = "MEMBER"
        elif revocation == "project":
            db.get(Project, world["projects"]["a"].id).is_active = False
        else:
            db.get(User, world["users"]["manager"].id).company_id = world["users"][
                "outsider"
            ].company_id
        db.commit()
    assert client.get(f"/api/v1/invoices/{invoice['id']}").status_code == 404
    assert client.get(invoice["attachment"]["url"]).status_code == 404
    assert act(client, invoice, "APPROVE").status_code == 404


@pytest.mark.parametrize("role", ["PROJECT_MANAGER", "FINANCE_MANAGER"])
def test_creator_cannot_review_after_role_change(client, world, role):
    invoice = act(client, ready(client, world)).json()
    if role == "FINANCE_MANAGER":
        login(client, world, "manager")
        invoice = act(client, invoice, "APPROVE").json()
    with Session(world["admin_engine"]) as db:
        db.get(User, world["users"]["employee"].id).role = role
        db.get(
            ProjectMember, (world["projects"]["a"].id, world["users"]["employee"].id)
        ).membership_role = "MANAGER"
        db.commit()
    login(client, world)
    assert current(client, invoice)["workflow"]["allowed_actions"] == []
    assert act(client, invoice, "APPROVE").status_code == 403


def test_project_approver_cannot_also_approve_finance(client, world):
    invoice = act(client, ready(client, world)).json()
    login(client, world, "manager")
    invoice = act(client, invoice, "APPROVE").json()
    with Session(world["admin_engine"]) as db:
        db.get(User, world["users"]["manager"].id).role = "FINANCE_MANAGER"
        db.commit()
    assert current(client, invoice)["workflow"]["allowed_actions"] == []
    assert act(client, invoice, "APPROVE").status_code == 403


@pytest.mark.parametrize("failure", ["file", "totals"])
def test_submission_checks_original_and_recalculates_saved_values(client, world, failure):
    invoice = ready(client, world)
    with Session(world["admin_engine"]) as db:
        if failure == "file":
            attachment = db.scalar(select(Attachment).where(Attachment.invoice_id == invoice["id"]))
            (get_settings().upload_dir / attachment.storage_key).unlink()
        else:
            db.get(Invoice, invoice["id"]).grand_total = 1
            db.commit()
    assert act(client, invoice).status_code == 422
    assert current(client, invoice)["status"] == "DRAFT"


def test_failed_review_rolls_back_state_revision_and_audit(client, world, monkeypatch):
    invoice = act(client, ready(client, world)).json()
    login(client, world, "manager")
    before = current(client, invoice)

    def fail_commit(self):
        raise RuntimeError("Simulated review commit failure")

    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", fail_commit)
        assert act(client, invoice, "APPROVE").status_code == 500
    assert current(client, invoice) == before


def test_explicit_zero_total_can_be_submitted(client, world):
    invoice = ready(client, world)
    zero = save(
        client,
        invoice,
        payload(
            invoice,
            supplier_id=invoice["supplier"]["id"],
            items=[item(unit_price="0", discount_amount="0", tax_rate="0")],
        ),
    ).json()
    assert zero["totals"]["grand_total"] == "0.00"
    assert act(client, zero).json()["status"] == "PROJECT_REVIEW"


@pytest.mark.parametrize("restriction", ["company", "inactive_project"])
def test_finance_cannot_read_or_act_outside_current_scope(client, world, restriction):
    invoice = act(client, ready(client, world)).json()
    login(client, world, "manager")
    invoice = act(client, invoice, "APPROVE").json()
    login(client, world, "finance")
    with Session(world["admin_engine"]) as db:
        if restriction == "company":
            db.get(User, world["users"]["finance"].id).company_id = world["users"][
                "outsider"
            ].company_id
        else:
            db.get(Project, world["projects"]["a"].id).is_active = False
        db.commit()
    assert client.get("/api/v1/invoices").json()["total"] == 0
    assert client.get(f"/api/v1/invoices/{invoice['id']}").status_code == 404
    assert client.get(invoice["attachment"]["url"]).status_code == 404
    assert act(client, invoice, "APPROVE").status_code == 404
