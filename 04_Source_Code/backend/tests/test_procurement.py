import json
import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_financial_audit import audit_check
from test_first_increment import pdf_bytes, upload, xml_bytes
from test_invoice_data import item, payload, save

from app.core.config import get_settings
from app.core.database import engine
from app.models import ProcurementAuditLog, ReceiptAttachment
from conftest import login


def create_supplier(client, name=None):
    response = client.post(
        "/api/v1/suppliers",
        json={"name": name or f"Procurement supplier {uuid.uuid4()}", "tax_number": "PO-TAX"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def order_payload(world, supplier, **changes):
    return {
        "project_id": str(world["projects"]["a"].id),
        "supplier_id": supplier["id"],
        "number": f"PO-{uuid.uuid4().hex[:8]}",
        "order_date": "2026-09-12",
        "currency": "SAR",
        "items": [
            {
                "description": "Ordered material",
                "unit": "piece",
                "ordered_quantity": "10",
                "unit_price": "100",
                "tax_rate": "15",
            }
        ],
        **changes,
    }


def create_order(client, world, supplier, **changes):
    login(client, world, "finance")
    response = client.post(
        "/api/v1/purchase-orders", json=order_payload(world, supplier, **changes)
    )
    assert response.status_code == 201, response.text
    return response.json()


def add_receipt(client, order, *, number=None, quantity="4", item_id=None, content=None):
    data = {
        "number": number or f"GR-{uuid.uuid4().hex[:8]}",
        "received_date": "2026-09-12",
        "note": "Delivery inspected",
        "items": [
            {
                "purchase_order_item_id": str(item_id or order["items"][0]["id"]),
                "received_quantity": quantity,
            }
        ],
    }
    return client.post(
        f"/api/v1/purchase-orders/{order['id']}/receipts",
        data={"receipt_data": json.dumps(data)},
        files={
            "file": (
                "delivery-note.pdf",
                pdf_bytes() if content is None else content,
                "application/octet-stream",
            )
        },
    )


def test_purchase_orders_are_finance_created_and_project_scoped(client, world):
    login(client, world)
    supplier = create_supplier(client)
    data = order_payload(world, supplier, number="PO ٠٠١")
    assert client.post("/api/v1/purchase-orders", json=data).status_code == 403

    login(client, world, "finance")
    created = client.post("/api/v1/purchase-orders", json=data)
    assert created.status_code == 201, created.text
    order = created.json()
    assert order["number"] == "PO ٠٠١"
    assert order["totals"]["grand_total"] == "1150.00"
    assert order["items"][0]["received_quantity"] == "0.0000"
    assert (
        client.post("/api/v1/purchase-orders", json={**data, "number": "po-001"}).status_code == 409
    )

    for user, count in (("employee", 1), ("manager", 1), ("manager_b", 0), ("outsider", 0)):
        login(client, world, user)
        assert len(client.get("/api/v1/purchase-orders").json()) == count


def test_receipt_evidence_is_private_validated_and_append_only(client, world):
    login(client, world)
    supplier = create_supplier(client)
    order = create_order(client, world, supplier)
    login(client, world)
    receipt = add_receipt(client, order, number="GR-001")
    assert receipt.status_code == 201, receipt.text
    current = receipt.json()
    assert current["items"][0]["received_quantity"] == "4.0000"
    assert current["receipts"][0]["note"] == "Delivery inspected"
    evidence_url = current["receipts"][0]["evidence"]["url"]
    assert client.get(evidence_url).content == pdf_bytes()
    assert "attachment" in client.get(evidence_url).headers["content-disposition"]

    assert add_receipt(client, order, number="GR 001").status_code == 409
    assert add_receipt(client, order, content=xml_bytes()).status_code == 422
    assert add_receipt(client, order, item_id=uuid.uuid4()).status_code == 422
    assert len(list((get_settings().upload_dir / "receipts").iterdir())) == 1

    login(client, world, "manager")
    assert client.get(evidence_url).status_code == 200
    assert add_receipt(client, order).status_code == 403
    login(client, world, "manager_b")
    assert client.get(evidence_url).status_code == 404
    login(client, world, "outsider")
    assert client.get(evidence_url).status_code == 404

    with Session(world["admin_engine"]) as db:
        assert db.scalar(select(func.count()).select_from(ProcurementAuditLog)) == 2
        assert db.scalar(select(func.count()).select_from(ReceiptAttachment)) == 1
    with engine.connect() as connection:
        with pytest.raises(DBAPIError):
            connection.execute(text("DELETE FROM procurement_audit_logs"))
        connection.rollback()


def test_invoice_matches_order_receipt_and_cumulative_quantities(client, world):
    login(client, world)
    supplier = create_supplier(client)
    order = create_order(client, world, supplier)
    login(client, world)
    assert add_receipt(client, order, quantity="4").status_code == 201
    invoice = upload(client, world).json()
    linked = payload(
        invoice,
        supplier_id=supplier["id"],
        purchase_order_id=order["id"],
        items=[
            item(
                quantity="4",
                purchase_order_item_id=order["items"][0]["id"],
            )
        ],
    )
    invoice = save(client, invoice, linked).json()
    assert invoice["purchase_order"]["number"] == order["number"]
    assert invoice["items"][0]["purchase_order_item_position"] == 1
    for code in ("PURCHASE_ORDER_HEADER", "PURCHASE_ORDER_LINES", "GOODS_RECEIPT_MATCH"):
        assert audit_check(invoice, code)["status"] == "PASS"
    replay = save(client, invoice, {**linked, "revision": invoice["revision"]}).json()
    assert replay["revision"] == invoice["revision"]

    submit = client.post(
        f"/api/v1/invoices/{invoice['id']}/workflow",
        json={"action": "SUBMIT", "revision": invoice["revision"], "confirmed": True},
    )
    assert submit.status_code == 200, submit.text

    login(client, world, "peer")
    second = upload(client, world, content=pdf_bytes() + b"\nsecond").json()
    second = save(
        client,
        second,
        payload(
            second,
            supplier_id=supplier["id"],
            invoice_number="PO-SECOND",
            purchase_order_id=order["id"],
            items=[
                item(
                    quantity="7",
                    purchase_order_item_id=order["items"][0]["id"],
                )
            ],
        ),
    ).json()
    line_check = audit_check(second, "PURCHASE_ORDER_LINES")
    receipt_check = audit_check(second, "GOODS_RECEIPT_MATCH")
    assert line_check["status"] == "WARNING"
    assert (
        next(
            value
            for value in line_check["comparisons"]
            if value["field"] == "purchase_order_quantity"
        )["invoice_value"]
        == "11.0000"
    )
    assert receipt_check["status"] == "WARNING"
    assert receipt_check["match_count"] == 1


def test_invoice_rejects_cross_order_item_and_reports_missing_links(client, world):
    login(client, world)
    supplier = create_supplier(client)
    first = create_order(client, world, supplier)
    second = create_order(client, world, supplier)
    login(client, world)
    invoice = upload(client, world).json()
    invalid = payload(
        invoice,
        supplier_id=supplier["id"],
        purchase_order_id=first["id"],
        items=[item(purchase_order_item_id=second["items"][0]["id"])],
    )
    assert save(client, invoice, invalid).status_code == 422
    unlinked = save(
        client,
        invoice,
        payload(invoice, supplier_id=supplier["id"], purchase_order_id=first["id"]),
    ).json()
    assert audit_check(unlinked, "PURCHASE_ORDER_LINES")["status"] == "WARNING"
    assert audit_check(unlinked, "GOODS_RECEIPT_MATCH")["status"] == "NOT_CHECKED"
