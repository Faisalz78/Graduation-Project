import pytest
from sqlalchemy import select
from test_first_increment import pdf_bytes, upload
from test_invoice_data import payload, save

from app.core.database import SessionLocal
from app.models import Attachment, ExtractionJob, Invoice
from conftest import login


def audit_check(invoice, code):
    return next(check for check in invoice["audit"]["checks"] if check["code"] == code)


def create_supplier(client, name="Financial audit supplier", region_code=None):
    response = client.post(
        "/api/v1/suppliers",
        json={"name": name, "tax_number": "TEST-TAX", "region_code": region_code},
    )
    assert response.status_code == 201, response.text
    return response.json()


def add_structured_result(invoice_id, requested_by, sources):
    with SessionLocal() as db:
        invoice = db.get(Invoice, invoice_id)
        attachment = db.scalar(select(Attachment).where(Attachment.invoice_id == invoice.id))
        db.add(
            ExtractionJob(
                invoice_id=invoice.id,
                requested_by=requested_by,
                attachment_id=attachment.id,
                source_sha256=attachment.sha256,
                base_revision=invoice.revision,
                language="ar",
                status="SUCCEEDED",
                attempts=1,
                result={
                    "reader_version": "test-only",
                    "parser_version": "test-only",
                    "fields": {},
                    "items": [],
                    "warnings": [],
                    "requires_human_review": True,
                    "structured_sources": sources,
                },
            )
        )
        db.commit()


def structured_source(source_type, fields, *, document_type=None):
    return {
        "type": source_type,
        "document_type": document_type or ("ZATCA_TLV" if source_type == "QR" else "Invoice"),
        "fields": {
            name: {"value": value, "evidence": f"test/{name}"} for name, value in fields.items()
        },
    }


def test_document_totals_are_compared_to_calculated_lines_and_recorded(client, world):
    login(client, world)
    invoice = upload(client, world).json()
    supplier = create_supplier(client)
    matching = save(
        client,
        invoice,
        payload(
            invoice,
            supplier_id=supplier["id"],
            document_totals={
                "subtotal": "190.00",
                "tax_total": "28.50",
                "grand_total": "218.50",
            },
        ),
    )
    assert matching.status_code == 200, matching.text
    result = matching.json()
    assert result["document_totals"] == {
        "subtotal": "190.00",
        "tax_total": "28.50",
        "grand_total": "218.50",
    }
    assert result["audit"]["summary"] == "PASS"
    for code in ("DOCUMENT_SUBTOTAL", "DOCUMENT_TAX_TOTAL", "DOCUMENT_GRAND_TOTAL"):
        assert audit_check(result, code)["status"] == "PASS"

    changed = save(
        client,
        result,
        payload(
            result,
            supplier_id=supplier["id"],
            document_totals={
                "subtotal": "190.00",
                "tax_total": "30.00",
                "grand_total": "220.00",
            },
        ),
    ).json()
    assert changed["audit"]["summary"] == "NEEDS_REVIEW"
    tax = audit_check(changed, "DOCUMENT_TAX_TOTAL")
    assert tax["status"] == "WARNING"
    assert tax["document_value"] == "30.00"
    assert tax["calculated_value"] == "28.50"
    assert tax["difference"] == "1.50"
    event = changed["events"][-1]
    assert event["details"]["before"]["document_totals"]["tax_total"] == "28.50"
    assert event["details"]["after"]["document_totals"]["tax_total"] == "30.00"


@pytest.mark.parametrize(
    "value",
    [-1, "-1", "1.001", "NaN", 1.25, True, "1000000000000001"],
)
def test_invalid_document_totals_are_rejected_without_mutation(client, world, value):
    login(client, world)
    invoice = upload(client, world).json()
    response = save(
        client,
        invoice,
        payload(
            invoice,
            document_totals={"subtotal": value, "tax_total": None, "grand_total": None},
        ),
    )
    assert response.status_code == 422
    current = client.get(f"/api/v1/invoices/{invoice['id']}").json()
    assert current["revision"] == 1
    assert current["document_totals"] is None


def test_partial_document_totals_are_explicitly_incomplete(client, world):
    login(client, world)
    invoice = upload(client, world).json()
    result = save(
        client,
        invoice,
        payload(
            invoice,
            document_totals={"subtotal": None, "tax_total": None, "grand_total": "218.50"},
        ),
    ).json()
    assert result["audit"]["summary"] == "INCOMPLETE"
    assert audit_check(result, "DOCUMENT_GRAND_TOTAL")["status"] == "PASS"
    assert audit_check(result, "DOCUMENT_SUBTOTAL")["status"] == "NOT_CHECKED"


def test_exact_and_financial_duplicates_are_flagged_without_leaking_private_invoice(client, world):
    content = pdf_bytes()
    login(client, world)
    first = upload(client, world, content=content).json()
    supplier = create_supplier(client, "Shared financial audit supplier")
    first = save(
        client,
        first,
        payload(first, supplier_id=supplier["id"], invoice_number="INV-٠٠١"),
    ).json()
    assert audit_check(first, "EXACT_FILE_DUPLICATE")["status"] == "PASS"
    assert audit_check(first, "POTENTIAL_DUPLICATE")["status"] == "PASS"

    login(client, world, "peer")
    second = upload(client, world, content=content).json()
    second = save(
        client,
        second,
        payload(second, supplier_id=supplier["id"], invoice_number="inv 001"),
    ).json()
    assert second["audit"]["summary"] == "NEEDS_REVIEW"
    assert audit_check(second, "EXACT_FILE_DUPLICATE")["match_count"] == 1
    assert audit_check(second, "POTENTIAL_DUPLICATE")["match_count"] == 1

    login(client, world)
    first = client.get(f"/api/v1/invoices/{first['id']}").json()
    assert audit_check(first, "EXACT_FILE_DUPLICATE")["status"] == "WARNING"
    assert audit_check(first, "POTENTIAL_DUPLICATE")["status"] == "WARNING"
    assert second["id"] not in str(first["audit"])


def test_duplicate_checks_do_not_cross_company_boundaries(client, world):
    content = pdf_bytes()
    login(client, world)
    invoice = upload(client, world, content=content).json()
    login(client, world, "outsider")
    assert upload(client, world, content=content, project="other").status_code == 201
    login(client, world)
    result = client.get(f"/api/v1/invoices/{invoice['id']}").json()
    assert audit_check(result, "EXACT_FILE_DUPLICATE")["status"] == "PASS"
    assert audit_check(result, "EXACT_FILE_DUPLICATE")["match_count"] == 0


def test_qr_and_xml_sources_are_compared_to_confirmed_invoice_data(client, world):
    login(client, world)
    invoice = upload(client, world).json()
    supplier = create_supplier(client, "Structured source supplier")
    invoice = save(
        client,
        invoice,
        payload(
            invoice,
            supplier_id=supplier["id"],
            document_totals={
                "subtotal": "190.00",
                "tax_total": "28.50",
                "grand_total": "218.50",
            },
        ),
    ).json()
    add_structured_result(
        invoice["id"],
        world["users"]["employee"].id,
        [
            structured_source(
                "QR",
                {
                    "supplier_tax_number": "310123456700003",
                    "invoice_date": "2026-09-11",
                    "tax_total": "28.50",
                    "grand_total": "218.50",
                },
            ),
            structured_source(
                "XML",
                {
                    "supplier_tax_number": "TEST-TAX",
                    "invoice_number": "TEST-001",
                    "invoice_date": "2026-09-11",
                    "currency": "SAR",
                    "subtotal": "190.00",
                    "tax_total": "28.50",
                    "grand_total": "220.00",
                },
            ),
        ],
    )
    result = client.get(f"/api/v1/invoices/{invoice['id']}").json()
    qr = audit_check(result, "QR_SOURCE_COMPARISON")
    xml = audit_check(result, "XML_SOURCE_COMPARISON")
    assert qr["status"] == "WARNING" and qr["source_count"] == 1
    assert (
        next(c for c in qr["comparisons"] if c["field"] == "supplier_tax_number")["status"]
        == "MISMATCH"
    )
    assert xml["status"] == "WARNING" and xml["source_count"] == 1
    mismatch = next(c for c in xml["comparisons"] if c["field"] == "grand_total")
    assert mismatch == {
        "field": "grand_total",
        "label": "الإجمالي شامل الضريبة",
        "source_value": "220.00",
        "invoice_value": "218.50",
        "status": "MISMATCH",
    }


def test_structured_checks_are_incomplete_until_a_source_is_read(client, world):
    login(client, world)
    result = upload(client, world).json()
    current = client.get(f"/api/v1/invoices/{result['id']}").json()
    for code in ("QR_SOURCE_COMPARISON", "XML_SOURCE_COMPARISON"):
        check = audit_check(current, code)
        assert check["status"] == "NOT_CHECKED"
        assert check["source_count"] == 0 and check["comparisons"] == []
