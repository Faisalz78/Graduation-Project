import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_invoice_data import draft, item, payload, save
from test_workflow import act, ready

from app.core.database import engine
from app.models import ApprovalLimitAuditLog, SupplierAuditLog
from conftest import login


def audit_check(invoice, code):
    return next(check for check in invoice["audit"]["checks"] if check["code"] == code)


def test_finance_manages_peer_limits_with_separation_and_audit(client, world):
    login(client, world)
    assert client.get("/api/v1/governance/approval-limits").status_code == 403

    login(client, world, "finance")
    rows = client.get("/api/v1/governance/approval-limits")
    assert rows.status_code == 200
    assert {row["user"]["role"] for row in rows.json()} == {
        "PROJECT_MANAGER",
        "FINANCE_MANAGER",
    }
    assert (
        client.put(
            f"/api/v1/governance/approval-limits/{world['users']['finance'].id}/SAR",
            json={"amount": "500.00"},
        ).status_code
        == 403
    )
    updated = client.put(
        f"/api/v1/governance/approval-limits/{world['users']['manager'].id}/SAR",
        json={"amount": "1250.50"},
    )
    assert updated.status_code == 200, updated.text
    manager = next(
        row for row in updated.json() if row["user"]["id"] == str(world["users"]["manager"].id)
    )
    assert manager["limits"]["SAR"] == "1250.50"
    with Session(world["admin_engine"]) as db:
        assert db.scalar(select(func.count()).select_from(ApprovalLimitAuditLog)) == 1
    with engine.connect() as connection:
        with pytest.raises(DBAPIError):
            connection.execute(text("DELETE FROM approval_limit_audit_logs"))
        connection.rollback()


def test_invoice_over_limit_cannot_be_approved_but_can_be_returned(client, world):
    invoice = act(client, ready(client, world)).json()
    login(client, world, "finance")
    response = client.put(
        f"/api/v1/governance/approval-limits/{world['users']['manager'].id}/SAR",
        json={"amount": "100.00"},
    )
    assert response.status_code == 200

    login(client, world, "manager")
    current = client.get(f"/api/v1/invoices/{invoice['id']}").json()
    authority = current["workflow"]["approval_authority"]
    assert authority["can_approve"] is False
    assert authority["limit"] == "100.00"
    assert current["workflow"]["allowed_actions"] == ["REQUEST_CHANGES", "REJECT"]
    assert act(client, current, "APPROVE").status_code == 403
    returned = act(client, current, "REQUEST_CHANGES", comment="يتجاوز حد الموافقة")
    assert returned.status_code == 200
    assert returned.json()["status"] == "CHANGES_REQUESTED"


def test_supplier_internal_verification_is_controlled_and_visible_in_audit(client, world):
    login(client, world)
    supplier = client.post(
        "/api/v1/suppliers",
        json={"name": "Verified supplier", "tax_number": "310123456700003"},
    ).json()
    supplier_without_tax = client.post(
        "/api/v1/suppliers",
        json={"name": "Supplier without tax number"},
    ).json()
    invoice = draft(client, world)
    invoice = save(client, invoice, payload(invoice, supplier_id=supplier["id"])).json()
    assert audit_check(invoice, "SUPPLIER_VERIFICATION")["status"] == "NOT_CHECKED"
    assert (
        client.put(
            f"/api/v1/suppliers/{supplier['id']}/verification",
            json={"status": "VERIFIED", "note": "Reviewed"},
        ).status_code
        == 403
    )

    login(client, world, "finance")
    missing_tax = client.put(
        f"/api/v1/suppliers/{supplier_without_tax['id']}/verification",
        json={"status": "VERIFIED", "note": "Reviewed"},
    )
    assert missing_tax.status_code == 422
    verified = client.put(
        f"/api/v1/suppliers/{supplier['id']}/verification",
        json={"status": "VERIFIED", "note": "طابقنا الرقم الضريبي مع مستند المورد"},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["verification_status"] == "VERIFIED"
    assert verified.json()["verified_by"]["id"] == str(world["users"]["finance"].id)
    with Session(world["admin_engine"]) as db:
        assert db.scalar(select(func.count()).select_from(SupplierAuditLog)) == 1
    with engine.connect() as connection:
        with pytest.raises(DBAPIError):
            connection.execute(text("DELETE FROM supplier_audit_logs"))
        connection.rollback()

    login(client, world)
    current = client.get(f"/api/v1/invoices/{invoice['id']}").json()
    assert current["supplier"]["verification_status"] == "VERIFIED"
    assert audit_check(current, "SUPPLIER_VERIFICATION")["status"] == "PASS"


def test_credit_note_requires_matching_submitted_original_and_flags_over_credit(client, world):
    original = ready(client, world)
    original = act(client, original).json()
    note = draft(client, world)
    options = client.get(f"/api/v1/invoices/{note['id']}/related-options").json()
    assert [option["id"] for option in options] == [original["id"]]

    response = save(
        client,
        note,
        payload(
            note,
            supplier_id=original["supplier"]["id"],
            document_type="CREDIT_NOTE",
            related_invoice_id=original["id"],
            items=[item(unit_price="300", discount_amount="0")],
        ),
    )
    assert response.status_code == 200, response.text
    credit = response.json()
    assert credit["document_type"] == "CREDIT_NOTE"
    assert credit["related_document"]["invoice_number"] == original["invoice_number"]
    relation = audit_check(credit, "RELATED_FINANCIAL_DOCUMENT")
    assert relation["status"] == "WARNING"
    assert relation["calculated_value"].startswith("-")

    invalid = draft(client, world)
    invalid_response = save(
        client,
        invalid,
        payload(invalid, document_type="CREDIT_NOTE", related_invoice_id=None),
    )
    assert invalid_response.status_code == 422
