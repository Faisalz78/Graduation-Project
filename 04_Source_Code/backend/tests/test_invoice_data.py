from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_first_increment import upload

from app.core.config import get_settings
from app.main import app
from app.models import AuditLog, InvoiceItem
from conftest import login


def item(**changes):
    return {
        "description": "Test material",
        "unit": "piece",
        "quantity": "2",
        "unit_price": "100",
        "discount_amount": "10",
        "tax_rate": "15",
        **changes,
    }


def payload(invoice, **changes):
    return {
        "revision": invoice["revision"],
        "supplier_id": None,
        "invoice_number": "TEST-001",
        "invoice_date": "2026-09-10",
        "currency": "SAR",
        "note": "Manual test",
        "items": [item()],
        **changes,
    }


def draft(client, world):
    login(client, world)
    response = upload(client, world)
    assert response.status_code == 201
    return response.json()


def save(client, invoice, data):
    return client.put(f"/api/v1/invoices/{invoice['id']}", json=data)


def test_suppliers_are_company_scoped_and_duplicates_do_not_create_twice(client, world):
    login(client, world)
    created = client.post(
        "/api/v1/suppliers", json={"name": "  Test   Supplier ", "tax_number": ""}
    )
    assert created.status_code == 201
    assert created.json()["tax_number"] is None
    assert created.json()["verification_status"] == "UNVERIFIED"
    assert client.post("/api/v1/suppliers", json={"name": "test supplier"}).status_code == 409
    login(client, world, "manager")
    assert len(client.get("/api/v1/suppliers").json()) == 1
    assert client.post("/api/v1/suppliers", json={"name": "Other supplier"}).status_code == 403
    login(client, world, "finance")
    assert client.post("/api/v1/suppliers", json={"name": "Finance supplier"}).status_code == 201
    login(client, world, "outsider")
    assert client.get("/api/v1/suppliers").json() == []
    assert client.post("/api/v1/suppliers", json={"name": "test supplier"}).status_code == 201


def test_supplier_region_is_validated_and_returned(client, world):
    login(client, world)
    created = client.post(
        "/api/v1/suppliers",
        json={"name": "Regional Supplier", "region_code": "RIYADH"},
    )
    assert created.status_code == 201
    assert created.json()["region_code"] == "RIYADH"
    assert created.json()["region_name"] == "الرياض"
    invalid = client.post(
        "/api/v1/suppliers",
        json={"name": "Unknown Regional Supplier", "region_code": "UNKNOWN"},
    )
    assert invalid.status_code == 422


def test_legacy_draft_has_no_invented_financial_values_and_supports_partial_save(client, world):
    invoice = draft(client, world)
    for field in ("supplier", "invoice_number", "invoice_date", "currency", "totals"):
        assert invoice[field] is None
    assert invoice["items"] == []
    result = save(
        client, invoice, payload(invoice, items=[], currency=None, invoice_date=None)
    ).json()
    assert result["revision"] == 2 and result["invoice_number"] == "TEST-001"
    assert result["totals"] is None


def test_exact_line_rounding_snapshot_history_noop_and_original_file(client, world):
    invoice = draft(client, world)
    original = client.get(invoice["attachment"]["url"]).content
    supplier = client.post(
        "/api/v1/suppliers", json={"name": "Manual supplier", "tax_number": "TEST-TAX"}
    ).json()
    data = payload(
        invoice,
        supplier_id=supplier["id"],
        items=[item(), item(quantity="3", unit_price="0.335", discount_amount="0")],
    )
    response = save(client, invoice, data)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["totals"] == {
        "subtotal": "201.01",
        "discount_total": "10.00",
        "net_total": "191.01",
        "tax_total": "28.65",
        "grand_total": "219.66",
    }
    assert result["items"][1]["gross_amount"] == "1.01"
    assert result["supplier"]["name"] == "Manual supplier"
    event = [e for e in result["events"] if e["action"] == "DRAFT_UPDATED"][0]
    assert event["details"]["before"]["totals"] is None
    assert event["details"]["after"]["totals"]["grand_total"] == "219.66"
    assert event["details"]["revision"] == result["revision"] == 2
    replay = save(client, result, {**data, "revision": result["revision"]}).json()
    assert replay["revision"] == 2 and len(replay["events"]) == 3
    assert client.get(invoice["attachment"]["url"]).content == original
    assert client.get(f"/api/v1/invoices/{invoice['id']}").json()["totals"] == result["totals"]
    # Removing every line clears amounts instead of representing unknown data as zero.
    cleared = save(client, result, payload(result, items=[])).json()
    assert cleared["items"] == [] and cleared["totals"] is None and cleared["revision"] == 3
    assert cleared["events"][-1]["details"]["before"]["items"][1]["gross_amount"] == "1.01"


@pytest.mark.parametrize(
    "change",
    [
        {"quantity": "0"},
        {"quantity": "-1"},
        {"unit_price": "-1"},
        {"tax_rate": "101"},
        {"discount_amount": "200.01"},
        {"quantity": "1.00001"},
        {"unit_price": "0.00001"},
        {"discount_amount": "0.001"},
        {"tax_rate": "0.00001"},
        {"quantity": "NaN"},
        {"unit_price": "Infinity"},
        {"quantity": "1e4"},
        {"quantity": True},
        {"unit_price": 0.1},
        {"description": "   "},
        {"description": "\u0000"},
        {"quantity": "1000001"},
    ],
)
def test_invalid_items_are_rejected_without_changing_invoice(client, world, change):
    invoice = draft(client, world)
    response = save(client, invoice, payload(invoice, items=[item(**change)]))
    assert response.status_code == 422, response.text
    current = client.get(f"/api/v1/invoices/{invoice['id']}").json()
    assert current["revision"] == 1 and current["items"] == [] and len(current["events"]) == 2


@pytest.mark.parametrize(
    "change",
    [
        {"currency": None},
        {"currency": "JPY"},
        {"invoice_date": "2026-02-30"},
        {"invoice_date": 0},
        {"grand_total": "0.01"},
        {"items": [item()] * 101},
    ],
)
def test_invalid_header_and_forged_totals_are_rejected(client, world, change):
    invoice = draft(client, world)
    assert save(client, invoice, payload(invoice, **change)).status_code == 422


def test_zero_totals_are_explicit_and_large_decimals_stay_exact(client, world):
    invoice = draft(client, world)
    zero = save(
        client,
        invoice,
        payload(invoice, items=[item(unit_price="0", discount_amount="0", tax_rate="0")]),
    ).json()
    assert zero["totals"]["grand_total"] == "0.00"
    large = save(
        client,
        zero,
        payload(
            zero,
            items=[
                item(
                    quantity="1000000",
                    unit_price="1000000000",
                    discount_amount="0.01",
                    tax_rate="0",
                )
            ],
        ),
    ).json()
    assert large["totals"]["grand_total"] == "999999999999999.99"


def test_calculation_preview_does_not_save_and_requires_scope_and_csrf(client, world):
    invoice = draft(client, world)
    url = f"/api/v1/invoices/{invoice['id']}/calculate"
    response = client.post(url, json={"currency": "SAR", "items": [item()]})
    assert response.json()["totals"]["grand_total"] == "218.50"
    assert client.get(f"/api/v1/invoices/{invoice['id']}").json()["revision"] == 1
    assert (
        client.post(
            url, json={"currency": "SAR", "items": [item()]}, headers={"X-CSRF-Token": "bad"}
        ).status_code
        == 403
    )
    login(client, world, "peer")
    assert client.post(url, json={"currency": "SAR", "items": [item()]}).status_code == 404


def test_out_of_scope_supplier_edit_and_stale_revision(client, world):
    login(client, world, "outsider")
    supplier = client.post("/api/v1/suppliers", json={"name": "Outside supplier"}).json()
    invoice = draft(client, world)
    assert save(client, invoice, payload(invoice, supplier_id=supplier["id"])).status_code == 404
    login(client, world, "peer")
    assert save(client, invoice, payload(invoice)).status_code == 404
    login(client, world, "finance")
    assert save(client, invoice, payload(invoice)).status_code == 403
    login(client, world)
    assert save(client, invoice, payload(invoice)).status_code == 200
    assert save(client, invoice, payload(invoice, invoice_number="stale")).status_code == 409
    assert client.get(f"/api/v1/invoices/{invoice['id']}").json()["invoice_number"] == "TEST-001"


def test_concurrent_edit_has_one_winner_and_one_conflict(client, world):
    invoice = draft(client, world)

    def request(number):
        with TestClient(app) as browser:
            browser.headers["Origin"] = get_settings().app_origin
            login(browser, world)
            return save(browser, invoice, payload(invoice, invoice_number=number)).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(request, ["A", "B"])) == [200, 409]
    current = client.get(f"/api/v1/invoices/{invoice['id']}").json()
    assert current["revision"] == 2 and len(current["events"]) == 3


def test_failed_update_rolls_back_items_amounts_and_audit(client, world, monkeypatch):
    invoice = draft(client, world)
    saved = save(client, invoice, payload(invoice)).json()

    def fail_commit(self):
        raise RuntimeError("Simulated commit failure")

    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", fail_commit)
        assert (
            save(client, saved, payload(saved, items=[item(unit_price="300")])).status_code == 500
        )
    current = client.get(f"/api/v1/invoices/{invoice['id']}").json()
    assert current == saved
    with Session(world["admin_engine"]) as db:
        assert (
            len(
                list(db.scalars(select(InvoiceItem).where(InvoiceItem.invoice_id == invoice["id"])))
            )
            == 1
        )
        assert (
            len(list(db.scalars(select(AuditLog).where(AuditLog.invoice_id == invoice["id"])))) == 3
        )
