from decimal import Decimal

from test_financial_audit import audit_check, create_supplier
from test_financial_intelligence import create_invoice
from test_invoice_data import draft, item, payload, save
from test_workflow import act

from conftest import login


def test_split_invoice_detection_uses_project_limit_and_explains_risk(client, world):
    login(client, world, "finance")
    response = client.put(
        f"/api/v1/governance/approval-limits/{world['users']['manager'].id}/SAR",
        json={"amount": "100.00"},
    )
    assert response.status_code == 200

    login(client, world)
    supplier = create_supplier(client, "مورد تجزئة مصطنع")
    first = create_invoice(
        client,
        world,
        supplier["id"],
        number="SPLIT-001",
        invoice_date="2026-09-10",
        price="60",
        submit=True,
    )
    second = create_invoice(
        client,
        world,
        supplier["id"],
        number="SPLIT-002",
        invoice_date="2026-09-12",
        price="60",
        submit=True,
    )

    split = audit_check(second, "SPLIT_INVOICE")
    assert split["status"] == "WARNING"
    assert split["document_value"] == "69.00"
    assert split["calculated_value"] == "138.00"
    assert split["match_count"] == 1
    assert split["split_analysis"] == {
        "window_days": 7,
        "document_count": 2,
        "combined_total": "138.00",
        "approval_threshold": "100.00",
        "all_documents_within_threshold": True,
        "privacy_note": "تعرض النتيجة عدد المستندات والمجموع دون أرقام الفواتير الأخرى أو أصحابها.",
    }
    assert second["audit"]["risk"]["level"] == "HIGH"
    assert any(factor["code"] == "SPLIT_INVOICE" for factor in second["audit"]["risk"]["factors"])
    assert (
        second["events"][-1]["details"]["audit_snapshot"]["risk"]["policy"]["version"]
        == "explainable-review-priority-v1"
    )

    login(client, world, "manager")
    first = client.get(f"/api/v1/invoices/{first['id']}").json()
    assert act(client, first, "APPROVE").status_code == 200


def test_dashboard_is_scoped_and_separates_approved_from_under_review(client, world):
    login(client, world)
    assert client.get("/api/v1/analytics/dashboard").status_code == 403
    supplier = create_supplier(client, "مورد لوحة مصطنع")
    approved = create_invoice(
        client,
        world,
        supplier["id"],
        number="DASH-APPROVED",
        invoice_date="2026-09-11",
        price="100",
        submit=True,
    )
    pending = create_invoice(
        client,
        world,
        supplier["id"],
        number="DASH-PENDING",
        invoice_date="2026-09-12",
        price="200",
        submit=True,
    )

    login(client, world, "manager")
    approved = act(client, approved, "APPROVE").json()
    login(client, world, "finance")
    approved = act(client, approved, "APPROVE").json()
    assert approved["status"] == "APPROVED"

    dashboard = client.get("/api/v1/analytics/dashboard?currency=SAR")
    assert dashboard.status_code == 200, dashboard.text
    data = dashboard.json()
    assert data["summary"]["document_count"] == 2
    assert data["summary"]["approved_document_count"] == 1
    assert Decimal(data["summary"]["approved_net"]) == Decimal("115.00")
    assert Decimal(data["summary"]["under_review_net"]) == Decimal("230.00")
    assert data["status_counts"]["APPROVED"] == 1
    assert data["status_counts"]["PROJECT_REVIEW"] == 1
    assert data["supplier_breakdown"][0]["supplier_name"] == "مورد لوحة مصطنع"
    assert data["supplier_breakdown"][0]["approved_net"] == "115.00"
    assert data["project_breakdown"][0]["approved_net"] == "115.00"
    assert data["project_breakdown"][0]["under_review_net"] == "230.00"
    assert any(row["amount"] == "115.00" for row in data["monthly_approved_net"])
    assert pending["id"] in {row["invoice_id"] for row in data["exception_queue"]}

    login(client, world, "manager_b")
    scoped = client.get("/api/v1/analytics/dashboard?currency=SAR").json()
    assert scoped["summary"]["document_count"] == 0
    assert [project["code"] for project in scoped["projects"]] == ["B"]
    assert (
        client.get(
            f"/api/v1/analytics/dashboard?currency=SAR&project_id={world['projects']['a'].id}"
        ).status_code
        == 404
    )


def test_dashboard_subtracts_approved_credit_notes_from_their_original(client, world):
    login(client, world)
    supplier = create_supplier(client, "مورد صافي الإشعارات")
    original = create_invoice(
        client,
        world,
        supplier["id"],
        number="NET-ORIGINAL",
        invoice_date="2026-09-10",
        price="100",
        submit=True,
    )
    login(client, world, "manager")
    original = act(client, original, "APPROVE").json()
    login(client, world, "finance")
    original = act(client, original, "APPROVE").json()

    login(client, world)
    credit = draft(client, world)
    credit = save(
        client,
        credit,
        payload(
            credit,
            supplier_id=supplier["id"],
            invoice_number="NET-CREDIT",
            invoice_date="2026-09-12",
            document_type="CREDIT_NOTE",
            related_invoice_id=original["id"],
            items=[item(quantity="1", unit_price="20", discount_amount="0")],
        ),
    ).json()
    credit = act(client, credit).json()
    login(client, world, "manager")
    credit = act(client, credit, "APPROVE").json()
    login(client, world, "finance")
    credit = act(client, credit, "APPROVE").json()
    assert credit["status"] == "APPROVED"

    data = client.get("/api/v1/analytics/dashboard?currency=SAR").json()
    assert data["summary"]["approved_document_count"] == 2
    assert data["summary"]["approved_net"] == "92.00"
    assert data["supplier_breakdown"][0]["approved_net"] == "92.00"
    assert any(item["amount"] == "92.00" for item in data["monthly_approved_net"])
