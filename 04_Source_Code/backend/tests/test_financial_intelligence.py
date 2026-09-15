from test_financial_audit import (
    add_structured_result,
    audit_check,
    create_supplier,
    structured_source,
)
from test_first_increment import upload
from test_invoice_data import item, payload, save
from test_workflow import act

from conftest import login


def create_invoice(
    client,
    world,
    supplier_id,
    *,
    number,
    invoice_date,
    price,
    description="كابل شبكة CAT6 بطول 10 متر",
    unit="قطعة",
    quantity="1",
    submit=False,
    user="employee",
    project="a",
):
    login(client, world, user)
    draft = upload(client, world, project=project, note="عينة مصطنعة للتحليل المالي").json()
    saved = save(
        client,
        draft,
        payload(
            draft,
            supplier_id=supplier_id,
            invoice_number=number,
            invoice_date=invoice_date,
            document_totals=None,
            items=[
                item(
                    description=description,
                    unit=unit,
                    quantity=quantity,
                    unit_price=str(price),
                    discount_amount="0",
                )
            ],
        ),
    )
    assert saved.status_code == 200, saved.text
    result = saved.json()
    if submit:
        result = act(client, result).json()
        assert result["status"] == "PROJECT_REVIEW"
    return result


def test_historical_price_anomaly_uses_distinct_submitted_invoices_and_explains_threshold(
    client, world
):
    login(client, world)
    supplier = create_supplier(client, "مورد تاريخ الأسعار")
    for index, price in enumerate(("90", "100", "110"), start=1):
        create_invoice(
            client,
            world,
            supplier["id"],
            number=f"HIST-{index}",
            invoice_date=f"2026-08-0{index}",
            price=price,
            description="كابل شبكة CAT-6 بطول 10 متر",
            unit="pcs",
            submit=True,
        )

    current = create_invoice(
        client,
        world,
        supplier["id"],
        number="CURRENT-PRICE",
        invoice_date="2026-09-12",
        price="160",
    )
    check = audit_check(current, "HISTORICAL_PRICE_ANOMALY")
    assert check["status"] == "WARNING"
    assert check["policy"] == {
        "lookback_days": 365,
        "minimum_invoices": 3,
        "minimum_increase_percent": "20.0",
        "baseline": "MEDIAN_AND_IQR",
        "price_basis": "AFTER_LINE_DISCOUNT_BEFORE_TAX",
    }
    finding = check["price_findings"][0]
    assert finding["status"] == "WARNING"
    assert finding["sample_count"] == finding["source_invoice_count"] == 3
    assert finding["median_unit_price"] == "100.0000"
    assert finding["lower_quartile"] == "95.0000"
    assert finding["upper_quartile"] == "105.0000"
    assert finding["alert_threshold"] == "120.0000"
    assert finding["difference_percent"] == "60.0"
    assert finding["confidence"] == "MEDIUM"


def test_price_analysis_ignores_drafts_old_history_other_units_and_other_companies(client, world):
    login(client, world)
    supplier = create_supplier(client, "مورد نطاق الأسعار")
    create_invoice(
        client,
        world,
        supplier["id"],
        number="ONLY-SUBMITTED",
        invoice_date="2026-09-01",
        price="100",
        submit=True,
    )
    create_invoice(
        client,
        world,
        supplier["id"],
        number="DRAFT-IGNORED",
        invoice_date="2026-09-02",
        price="100",
    )
    create_invoice(
        client,
        world,
        supplier["id"],
        number="UNIT-IGNORED",
        invoice_date="2026-09-03",
        price="100",
        unit="كيلوجرام",
        submit=True,
    )
    current = create_invoice(
        client,
        world,
        supplier["id"],
        number="NO-BASELINE",
        invoice_date="2026-09-12",
        price="300",
    )
    check = audit_check(current, "HISTORICAL_PRICE_ANOMALY")
    assert check["status"] == "NOT_CHECKED"
    assert check["price_findings"][0]["sample_count"] == 1
    assert "لا يصدر النظام حكمًا" in check["price_findings"][0]["message"]


def test_regional_supplier_comparison_uses_matching_submitted_items_and_region_median(
    client, world
):
    login(client, world)
    suppliers = [
        create_supplier(client, "مورد الرياض الأول", "RIYADH"),
        create_supplier(client, "مورد الرياض الثاني", "RIYADH"),
        create_supplier(client, "مورد الشرقية", "EASTERN"),
        create_supplier(client, "مورد الفاتورة الحالية", "RIYADH"),
    ]
    for index, (supplier, price) in enumerate(zip(suppliers[:3], ("100", "110", "90")), start=1):
        create_invoice(
            client,
            world,
            supplier["id"],
            number=f"REGION-{index}",
            invoice_date=f"2026-08-0{index}",
            price=price,
            description="كابل شبكة CAT-6 بطول 10 متر",
            unit="pcs",
            submit=True,
        )
    current = create_invoice(
        client,
        world,
        suppliers[3]["id"],
        number="REGION-CURRENT",
        invoice_date="2026-09-12",
        price="150",
    )
    check = audit_check(current, "REGIONAL_SUPPLIER_PRICE")
    assert check["status"] == "WARNING"
    assert check["policy"]["benchmark_scope"] == "INTERNAL_SUBMITTED_INVOICES"
    finding = check["regional_findings"][0]
    assert finding["status"] == "WARNING"
    assert finding["current_region_name"] == "الرياض"
    assert finding["current_region_median"] == "105.0000"
    assert finding["difference_percent"] == "42.9"
    assert finding["potential_saving"] == "45.0000"
    assert finding["sample_count"] == 3
    assert finding["supplier_count"] == 3
    assert finding["region_count"] == 2
    assert {row["region_code"] for row in finding["region_comparisons"]} == {
        "RIYADH",
        "EASTERN",
    }
    assert "invoice_id" not in str(check)
    assert "supplier_id" not in str(check)


def test_regional_supplier_comparison_explains_missing_region(client, world):
    login(client, world)
    supplier = create_supplier(client, "مورد بلا منطقة")
    current = create_invoice(
        client,
        world,
        supplier["id"],
        number="REGION-MISSING",
        invoice_date="2026-09-12",
        price="150",
    )
    check = audit_check(current, "REGIONAL_SUPPLIER_PRICE")
    assert check["status"] == "NOT_CHECKED"
    assert check["regional_findings"] == []
    assert "ومنطقته" in check["message"]


def test_zero_historical_median_does_not_create_a_misleading_percentage(client, world):
    login(client, world)
    supplier = create_supplier(client, "مورد عينات سعرية صفرية")
    for index in range(3):
        create_invoice(
            client,
            world,
            supplier["id"],
            number=f"ZERO-{index}",
            invoice_date=f"2026-08-0{index + 1}",
            price="0",
            submit=True,
        )
    current = create_invoice(
        client,
        world,
        supplier["id"],
        number="ZERO-CURRENT",
        invoice_date="2026-09-12",
        price="50",
    )
    finding = audit_check(current, "HISTORICAL_PRICE_ANOMALY")["price_findings"][0]
    assert finding["status"] == "NOT_CHECKED"
    assert finding["median_unit_price"] == "0.0000"
    assert finding["difference_percent"] is None
    assert "لا يمكن حساب نسبة ارتفاع" in finding["message"]


def test_approximate_duplicate_combines_fuzzy_signals_without_private_invoice_data(client, world):
    login(client, world)
    supplier = create_supplier(client, "مورد التشابه التقريبي")
    first = create_invoice(
        client,
        world,
        supplier["id"],
        number="INV-2026-0018",
        invoice_date="2026-09-10",
        price="100",
    )
    second = create_invoice(
        client,
        world,
        supplier["id"],
        number="INV-2026-OO18",
        invoice_date="2026-09-11",
        price="102",
        description="كابل شبكة CAT6 طول 10 متر",
        user="peer",
    )
    for invoice, user in ((first, "employee"), (second, "peer")):
        add_structured_result(
            invoice["id"],
            world["users"][user].id,
            [
                structured_source(
                    "XML",
                    {
                        "supplier_name": "مورد التشابه التقريبي",
                        "invoice_number": "INV-2026-0018",
                        "grand_total": "115.00",
                    },
                )
            ],
        )

    login(client, world)
    refreshed = client.get(f"/api/v1/invoices/{first['id']}").json()
    check = audit_check(refreshed, "APPROXIMATE_DUPLICATE")
    assert check["status"] == "WARNING" and check["match_count"] == 1
    assert check["max_similarity_percent"] >= check["similarity_threshold_percent"] == 85
    signals = {signal["code"]: signal for signal in check["similarity_signals"]}
    assert signals["SUPPLIER"]["score_percent"] == 100
    assert signals["DOCUMENT_CONTENT"]["score_percent"] == 100
    assert signals["LINE_CONTENT"]["available"] is True
    serialized = str(check)
    assert second["id"] not in serialized
    assert "INV-2026-OO18" not in serialized
    assert check["privacy_note"].startswith("تعرض النتيجة درجات")


def test_approximate_duplicate_requires_supplier_anchor_and_stays_company_scoped(client, world):
    login(client, world)
    supplier = create_supplier(client, "مورد مختلف داخل الشركة")
    current = create_invoice(
        client,
        world,
        supplier["id"],
        number="UNIQUE-700",
        invoice_date="2026-09-12",
        price="700",
        description="جهاز توجيه شبكي فئة 700",
    )
    login(client, world, "outsider")
    outsider_supplier = client.post(
        "/api/v1/suppliers", json={"name": "مورد مختلف داخل الشركة"}
    ).json()
    create_invoice(
        client,
        world,
        outsider_supplier["id"],
        number="UNIQUE-70O",
        invoice_date="2026-09-12",
        price="700",
        description="جهاز توجيه شبكي فئة 700",
        user="outsider",
        project="other",
    )
    login(client, world)
    check = audit_check(
        client.get(f"/api/v1/invoices/{current['id']}").json(), "APPROXIMATE_DUPLICATE"
    )
    assert check["status"] == "PASS"
    assert check["match_count"] == 0 and check["comparison_count"] == 0


def test_intelligence_checks_are_explicit_when_invoice_data_is_missing(client, world):
    login(client, world)
    draft = upload(client, world).json()
    price = audit_check(draft, "HISTORICAL_PRICE_ANOMALY")
    duplicate = audit_check(draft, "APPROXIMATE_DUPLICATE")
    assert price["status"] == duplicate["status"] == "NOT_CHECKED"
    assert price["price_findings"] == []
    assert duplicate["similarity_signals"] == []
