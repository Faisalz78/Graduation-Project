import csv
import io

from test_financial_audit import create_supplier
from test_financial_intelligence import create_invoice
from test_invoice_data import draft, payload, save
from test_project_budgets import create_budget
from test_workflow import act

from conftest import login


def csv_rows(response):
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert response.headers["content-type"].startswith("text/csv")
    return list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))


def test_invoice_register_export_is_scoped_filterable_and_excel_safe(client, world):
    login(client, world)
    supplier = client.post(
        "/api/v1/suppliers",
        json={"name": '=HYPERLINK("https://invalid.test")', "region_code": "RIYADH"},
    ).json()
    invoice = draft(client, world)
    saved = save(
        client,
        invoice,
        payload(
            invoice,
            supplier_id=supplier["id"],
            invoice_number="=CMD|test",
            invoice_date="2026-09-12",
        ),
    ).json()
    act(client, saved)

    login(client, world, "outsider")
    outsider_supplier = create_supplier(client, "شركة خارج النطاق", "EASTERN")
    create_invoice(
        client,
        world,
        outsider_supplier["id"],
        number="OUTSIDE",
        invoice_date="2026-09-12",
        price="10",
        submit=True,
        user="outsider",
        project="other",
    )

    login(client, world, "manager")
    response = client.get(
        "/api/v1/reports/invoices.csv",
        params={
            "project_id": str(world["projects"]["a"].id),
            "currency": "SAR",
            "status": "PROJECT_REVIEW",
            "date_from": "2026-09-01",
            "date_to": "2026-09-30",
        },
    )
    rows = csv_rows(response)
    assert "invoice-register-" in response.headers["content-disposition"]
    assert len(rows) == 2
    values = dict(zip(rows[0], rows[1]))
    assert values["رقم المستند"] == "'=CMD|test"
    assert values["المورد"].startswith("'=HYPERLINK")
    assert values["المشروع"] == "Project A"
    assert values["الحالة"] == "مراجعة المشروع"
    assert "OUTSIDE" not in response.text

    assert (
        client.get(
            "/api/v1/reports/invoices.csv",
            params={"date_from": "2026-10-01", "date_to": "2026-09-01"},
        ).status_code
        == 422
    )
    login(client, world, "manager_b")
    assert (
        client.get(
            "/api/v1/reports/invoices.csv",
            params={"project_id": str(world["projects"]["a"].id)},
        ).status_code
        == 404
    )
    login(client, world)
    assert client.get("/api/v1/reports/invoices.csv").status_code == 403


def test_budget_export_uses_the_same_defined_usage_and_project_scope(client, world):
    create_budget(client, world, total="1000.00")
    login(client, world, "manager")
    rows = csv_rows(
        client.get(
            "/api/v1/reports/budgets.csv",
            params={"project_id": str(world["projects"]["a"].id), "currency": "SAR"},
        )
    )
    assert len(rows) == 2
    values = dict(zip(rows[0], rows[1]))
    assert values["إجمالي الميزانية"] == "1000.00"
    assert values["المخصص للبنود"] == "500.00"
    assert values["الاحتياطي غير الموزع"] == "500.00"
    assert values["المتبقي"] == "1000.00"


def test_regional_price_export_contains_aggregates_without_reference_identities(client, world):
    login(client, world)
    suppliers = [
        create_supplier(client, "مرجع الرياض الأول", "RIYADH"),
        create_supplier(client, "مرجع الرياض الثاني", "RIYADH"),
        create_supplier(client, "مرجع الشرقية", "EASTERN"),
        create_supplier(client, "مورد التقرير الحالي", "RIYADH"),
    ]
    for index, (supplier, price) in enumerate(zip(suppliers[:3], ("100", "110", "90")), start=1):
        create_invoice(
            client,
            world,
            supplier["id"],
            number=f"REPORT-BASE-{index}",
            invoice_date=f"2026-08-0{index}",
            price=price,
            submit=True,
        )
    create_invoice(
        client,
        world,
        suppliers[3]["id"],
        number="REPORT-CURRENT",
        invoice_date="2026-09-12",
        price="150",
        submit=True,
    )
    login(client, world, "manager")
    response = client.get(
        "/api/v1/reports/regional-prices.csv",
        params={"currency": "SAR", "date_from": "2026-09-01"},
    )
    rows = csv_rows(response)
    current_rows = [dict(zip(rows[0], row)) for row in rows[1:] if row[0] == "REPORT-CURRENT"]
    assert {row["منطقة المقارنة"] for row in current_rows} == {
        "الرياض",
        "المنطقة الشرقية",
    }
    assert current_rows[0]["وسيط المنطقة الحالية"] == "105.0000"
    assert current_rows[0]["فرق السعر %"] == "42.9"
    assert "مرجع الرياض الأول" not in response.text
    assert "REPORT-BASE" not in response.text
