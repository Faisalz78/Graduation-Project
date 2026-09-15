import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_first_increment import xml_bytes
from test_invoice_data import draft, payload, save
from test_workflow import act, ready

from app.core.database import SessionLocal
from app.extraction_worker import claim, process, run_document
from app.models import Attachment, AuditLog, ExtractionJob, Invoice, User, utcnow
from conftest import login


def test_simultaneous_requests_create_one_job(client, world):
    from app.schemas.extraction import ExtractionRequest
    from app.services.extraction import request_extraction

    invoice = draft(client, world)

    def enqueue():
        with SessionLocal() as db:
            user = db.get(User, world["users"]["employee"].id)
            return request_extraction(
                db, user, uuid.UUID(invoice["id"]), ExtractionRequest(revision=1)
            )["id"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: enqueue(), range(2)))
    assert ids[0] == ids[1]


def test_submitted_invoice_cannot_start_or_apply_extraction(client, world):
    invoice = ready(client, world)
    queue(client, invoice)
    finish()
    response = act(client, invoice)
    assert response.status_code == 200
    sent = response.json()
    assert queue(client, sent).status_code == 409
    job = client.get(path(invoice)).json()["job"]
    assert job["is_stale"] and job["result"] is None


def test_failed_job_can_be_retried_after_cooldown(client, world):
    invoice = draft(client, world)
    first = queue(client, invoice).json()
    finish(lambda *args: {})  # Invalid output is persisted as a failure.
    assert queue(client, invoice).status_code == 429
    with SessionLocal() as db:
        db.get(ExtractionJob, uuid.UUID(first["id"])).created_at -= timedelta(seconds=11)
        db.commit()
    second = queue(client, invoice).json()
    assert second["id"] != first["id"] and second["status"] == "QUEUED"
    finish()
    assert client.get(path(invoice)).json()["job"]["status"] == "SUCCEEDED"


@pytest.mark.parametrize("box", [[-1, 0, 1, 1], [0, 0, 2, 1], [0.8, 0.1, 0.2, 0.3]])
def test_invalid_evidence_coordinates_are_rejected(client, world, box):
    invoice = draft(client, world)
    queue(client, invoice)
    output = result()
    output["fields"]["invoice_number"]["bbox"] = box
    finish(lambda *args: output)
    assert client.get(path(invoice)).json()["job"]["status"] == "FAILED"


@pytest.fixture(autouse=True)
def engine_available(monkeypatch):
    monkeypatch.setattr("app.services.extraction.available", lambda: True)


def path(invoice):
    return f"/api/v1/invoices/{invoice['id']}/extraction"


def queue(client, invoice, **changes):
    return client.post(
        path(invoice), json={"revision": invoice["revision"], "language": "ar", **changes}
    )


def result():
    return {
        "reader_version": "test-only",
        "parser_version": "test-only",
        "fields": {
            "invoice_number": {
                "value": "READ-123",
                "source": "PDF_TEXT",
                "page": 1,
                "bbox": [0.1, 0.1, 0.2, 0.2],
                "evidence": "Invoice No READ-123",
                "needs_review": True,
            }
        },
        "items": [],
        "warnings": [],
        "requires_human_review": True,
    }


def test_local_understanding_survives_worker_validation_without_editing_invoice(client, world):
    invoice = draft(client, world)
    queue(client, invoice)
    output = result()
    output["fields"]["invoice_number"]["interpretation"] = "LOCAL_VISION"
    output["local_understanding"] = {
        "model": "qwen3-vl:8b-instruct",
        "version": "grounded-local-vision-v1",
        "status": "PARTIAL",
        "pages": 1,
        "added_fields": 1,
        "confirmed_fields": 0,
        "added_rows": 0,
        "conflicts": 1,
        "rejected_values": 2,
        "seconds": 12.5,
    }
    output["image_preparation"] = [
        {
            "page": 1,
            "method": "ORIGINAL",
            "reread_regions": 3,
            "rotation": 0,
            "curvature_corrected": False,
        }
    ]
    finish(lambda *args: output)
    job = client.get(path(invoice)).json()["job"]
    assert job["status"] == "SUCCEEDED"
    assert job["result"]["local_understanding"] == output["local_understanding"]
    assert job["result"]["fields"]["invoice_number"]["interpretation"] == "LOCAL_VISION"
    assert job["result"]["image_preparation"] == output["image_preparation"]
    stored = client.get(f"/api/v1/invoices/{invoice['id']}").json()
    assert stored["revision"] == invoice["revision"]
    assert stored["invoice_number"] == invoice["invoice_number"]


def test_model_report_rejects_fake_confidence_and_invalid_counters():
    from pydantic import ValidationError

    from app.schemas.extraction import LocalUnderstanding

    data = dict(
        model="qwen3-vl:8b-instruct",
        version="v1",
        status="COMPLETED",
        pages=1,
        added_fields=1,
        confirmed_fields=1,
        added_rows=0,
        conflicts=0,
        rejected_values=0,
        seconds=1,
    )
    for change in ({"confidence": 1}, {"pages": 4}, {"seconds": float("nan")}, {"added_rows": 101}):
        with pytest.raises(ValidationError):
            LocalUnderstanding.model_validate({**data, **change})


def test_guided_regions_and_conflicting_evidence_are_preserved(client, world):
    invoice = draft(client, world)
    queue(client, invoice)
    output = result()
    evidence = output["fields"]["invoice_number"]
    output["conflict_details"] = [
        {
            "field": "invoice_number",
            "row": None,
            "reason": "DISAGREEMENT",
            "current": evidence,
            "proposed": {
                **evidence,
                "value": "ALTERNATE-123",
                "evidence": "ALTERNATE-123",
                "bbox": [0.2, 0.3, 0.5, 0.4],
            },
        }
    ]
    output["guided_reading"] = dict(
        attempted=1,
        completed=1,
        table_sections=0,
        recovered_tokens=2,
        status="COMPLETED",
        regions=[dict(page=1, kind="HEADER", bbox=[0.1, 0.1, 0.8, 0.3])],
    )
    finish(lambda *args: output)
    job = client.get(path(invoice)).json()["job"]
    assert job["status"] == "SUCCEEDED"
    assert job["result"]["fields"]["invoice_number"]["value"] == "READ-123"
    assert job["result"]["conflict_details"][0]["proposed"]["value"] == "ALTERNATE-123"
    assert job["result"]["guided_reading"] == output["guided_reading"]


def test_guided_report_rejects_bad_boxes_and_inconsistent_progress():
    from pydantic import ValidationError

    from app.schemas.extraction import GuidedReading

    data = dict(
        attempted=1,
        completed=1,
        table_sections=0,
        recovered_tokens=1,
        status="COMPLETED",
        regions=[dict(page=1, kind="TABLE", bbox=[0.1, 0.1, 0.8, 0.8])],
    )
    for change in (
        {"completed": 2},
        {"table_sections": 2},
        {"regions": []},
        {"regions": [dict(page=1, kind="TABLE", bbox=[0.9, 0.1, 0.2, 0.8])]},
    ):
        with pytest.raises(ValidationError):
            GuidedReading.model_validate({**data, **change})


def finish(runner=None):
    with SessionLocal() as db:
        work = claim(db)
    assert work
    process(*work, runner=runner or (lambda *args: result()))
    return work


def test_queue_is_idempotent_and_does_not_change_invoice(client, world):
    invoice = draft(client, world)
    response = queue(client, invoice)
    assert response.status_code == 200
    job = response.json()
    assert job["status"] == "QUEUED" and job["result"] is None
    assert queue(client, invoice).json()["id"] == job["id"]
    finish()
    read = client.get(path(invoice)).json()["job"]
    assert read["status"] == "SUCCEEDED" and not read["is_stale"]
    assert queue(client, invoice).json()["id"] == job["id"]
    current = client.get(f"/api/v1/invoices/{invoice['id']}").json()
    assert current["revision"] == invoice["revision"]
    assert current["invoice_number"] is None and current["items"] == []


def test_explicit_reread_preserves_previous_job_and_cooldown(client, world):
    invoice = draft(client, world)
    first = queue(client, invoice).json()
    finish()
    assert queue(client, invoice, force=True).status_code == 429
    with SessionLocal() as db:
        db.get(ExtractionJob, uuid.UUID(first["id"])).created_at -= timedelta(seconds=11)
        db.commit()
    second = queue(client, invoice, force=True).json()
    assert second["id"] != first["id"] and second["status"] == "QUEUED"
    assert queue(client, invoice, force=True).json()["id"] == second["id"]
    finish()
    with SessionLocal() as db:
        assert db.get(ExtractionJob, uuid.UUID(first["id"])).status == "SUCCEEDED"
        assert db.get(Invoice, uuid.UUID(invoice["id"])).revision == invoice["revision"]
        events = db.scalars(
            select(AuditLog).where(
                AuditLog.invoice_id == uuid.UUID(invoice["id"]),
                AuditLog.action == "EXTRACTION_REQUESTED",
            )
        ).all()
        assert len(events) == 2 and sum(event.details["force"] for event in events) == 1


@pytest.mark.parametrize("value", ["true", 1, None])
def test_reread_flag_is_strict(client, world, value):
    invoice = draft(client, world)
    assert queue(client, invoice, force=value).status_code == 422


@pytest.mark.parametrize("role", ["peer", "manager", "manager_b", "finance", "outsider"])
def test_extraction_is_private_to_owner(client, world, role):
    invoice = draft(client, world)
    queue(client, invoice)
    login(client, world, role)
    assert client.get(path(invoice)).status_code == 404
    assert queue(client, invoice).status_code == 404


def test_extraction_requires_csrf_and_strict_revision(client, world):
    invoice = draft(client, world)
    for value in (True, "1", 0):
        assert queue(client, invoice, revision=value).status_code == 422
    assert queue(client, invoice, language="xx").status_code == 422
    client.headers.pop("X-CSRF-Token")
    assert queue(client, invoice).status_code == 403


def test_worker_ignores_revision_changed_before_claim(client, world):
    invoice = draft(client, world)
    queue(client, invoice)
    assert save(client, invoice, payload(invoice)).status_code == 200

    def never(*args):
        pytest.fail("Stale job must not invoke OCR")

    finish(never)
    job = client.get(path(invoice)).json()["job"]
    assert job["status"] == "STALE" and job["result"] is None


def test_edit_during_extraction_discards_result(client, world):
    invoice = draft(client, world)
    queue(client, invoice)

    def during(*args):
        assert save(client, invoice, payload(invoice)).status_code == 200
        return result()

    finish(during)
    assert client.get(path(invoice)).json()["job"]["status"] == "STALE"


def test_revoked_user_cannot_finish_extraction(client, world):
    invoice = draft(client, world)
    queue(client, invoice)

    def during(*args):
        with Session(world["admin_engine"]) as db:
            db.get(User, world["users"]["employee"].id).is_active = False
            db.commit()
        return result()

    finish(during)
    with SessionLocal() as db:
        assert db.scalar(select(ExtractionJob)).status == "STALE"


@pytest.mark.parametrize(
    "failure,code",
    [
        (ValueError("PROCESS_FAILED"), "PROCESS_FAILED"),
        (subprocess.TimeoutExpired("test", 1), "TIMEOUT"),
        (ValueError("INVALID_RESULT"), "INVALID_RESULT"),
    ],
)
def test_failures_are_persisted_and_do_not_change_invoice(client, world, failure, code):
    invoice = draft(client, world)
    queue(client, invoice)

    def fail(*args):
        raise failure

    finish(fail)
    job = client.get(path(invoice)).json()["job"]
    assert job["status"] == "FAILED" and job["error"] and job["result"] is None
    with SessionLocal() as db:
        assert db.scalar(select(ExtractionJob)).error_code == code
        assert db.get(Invoice, uuid.UUID(invoice["id"])).revision == 1


def test_review_requires_confirmation_and_current_job(client, world):
    invoice = draft(client, world)
    job = queue(client, invoice).json()
    data = payload(invoice, extraction_job_id=job["id"], extraction_confirmed=True)
    assert save(client, invoice, data).status_code == 409
    finish()
    assert save(client, invoice, {**data, "extraction_confirmed": False}).status_code == 422
    assert save(client, invoice, {**data, "extraction_confirmed": "true"}).status_code == 422
    assert (
        save(client, invoice, {**data, "extraction_job_id": str(uuid.uuid4())}).status_code == 409
    )
    response = save(client, invoice, data)
    assert response.status_code == 200
    assert response.json()["invoice_number"] == "TEST-001"  # User correction, not OCR value.
    assert response.json()["revision"] == 2
    assert save(client, invoice, {**data, "revision": 2}).status_code == 409
    with SessionLocal() as db:
        event = db.scalar(select(AuditLog).where(AuditLog.action == "EXTRACTION_REVIEWED"))
        assert event.details["job_id"] == job["id"] and event.details["confirmed"]


def test_other_invoice_job_cannot_be_reviewed(client, world):
    invoice = draft(client, world)
    job = queue(client, invoice).json()
    finish()
    other = draft(client, world)
    assert (
        save(
            client, other, payload(other, extraction_job_id=job["id"], extraction_confirmed=True)
        ).status_code
        == 409
    )


def test_corrupt_source_is_not_processed_or_reviewed(client, world):
    from app.core.config import get_settings

    invoice = draft(client, world)
    job = queue(client, invoice).json()
    finish()
    with SessionLocal() as db:
        attachment = db.scalar(select(Attachment))
        (get_settings().upload_dir / attachment.storage_key).write_bytes(b"changed")
    assert (
        save(
            client,
            invoice,
            payload(invoice, extraction_job_id=job["id"], extraction_confirmed=True),
        ).status_code
        == 409
    )


def test_expired_attempt_is_reclaimed_and_old_attempt_cannot_overwrite(client, world):
    invoice = draft(client, world)
    queue(client, invoice)
    with SessionLocal() as db:
        first = claim(db)
        db.get(ExtractionJob, first[0]).lease_until = utcnow() - timedelta(seconds=1)
        db.commit()
        second = claim(db)
    assert second[0] == first[0] and second[1] != first[1]
    process(*first, runner=lambda *args: pytest.fail("Old attempt must not run"))
    process(*second, runner=lambda *args: result())
    job = client.get(path(invoice)).json()["job"]
    assert job["status"] == "SUCCEEDED" and job["attempts"] == 2


def test_second_interruption_finishes_as_failed(client, world):
    invoice = draft(client, world)
    queue(client, invoice)
    with SessionLocal() as db:
        work = claim(db)
        job = db.get(ExtractionJob, work[0])
        job.attempts = 2
        job.lease_until = utcnow() - timedelta(seconds=1)
        db.commit()
        assert claim(db) is None
    assert client.get(path(invoice)).json()["job"]["status"] == "FAILED"


def test_missing_engine_returns_actionable_error(client, world, monkeypatch):
    invoice = draft(client, world)
    monkeypatch.setattr("app.services.extraction.available", lambda: False)
    assert queue(client, invoice).status_code == 503


def test_direct_ubl_xml_runs_through_isolated_extractor_and_schema():
    output = run_document(xml_bytes(), "application/xml", "ar")
    assert output["fields"]["invoice_number"]["value"] == "XML-001"
    assert output["fields"]["invoice_number"]["source"] == "XML"
    assert output["structured_sources"][0]["document_type"] == "Invoice"


def test_private_inline_preview_preserves_default_download(client, world):
    invoice = draft(client, world)
    url = invoice["attachment"]["url"]
    response = client.get(url + "?inline=true")
    assert response.status_code == 200
    assert "inline" in response.headers["content-disposition"]
    assert response.headers["x-frame-options"] == "SAMEORIGIN"
    assert "attachment" in client.get(url).headers["content-disposition"]
    login(client, world, "peer")
    assert client.get(url + "?inline=true").status_code == 404


def hybrid_result():
    output = result()
    output.update(
        text="Invoice No READ-123",
        tokens=[
            {
                "text": "Invoice No READ-123",
                "confidence": None,
                "source": "PDF_TEXT",
                "page": 1,
                "bbox": [0.1, 0.1, 0.2, 0.2],
                "reading_order": 1,
                "line_number": 1,
            }
        ],
        page_routes=[
            {"page": 1, "method": "PDF_TEXT", "reason": "SEARCHABLE_TEXT", "image_coverage": 0}
        ],
    )
    return output


def test_hybrid_evidence_survives_worker_and_remains_private(client, world):
    invoice = draft(client, world)
    queue(client, invoice)
    finish(lambda *args: hybrid_result())
    data = client.get(path(invoice)).json()["job"]["result"]
    assert data["text"] == "Invoice No READ-123"
    assert data["tokens"][0]["reading_order"] == 1
    assert data["tokens"][0]["confidence"] is None
    assert data["page_routes"][0]["method"] == "PDF_TEXT"
    login(client, world, "peer")
    assert client.get(path(invoice)).status_code == 404


@pytest.mark.parametrize(
    "change", [{"reading_order": 2}, {"bbox": [0.9, 0, 0.1, 1]}, {"confidence": 0.99}, {"page": 4}]
)
def test_invalid_hybrid_evidence_is_rejected(change):
    from pydantic import ValidationError

    from app.schemas.extraction import ExtractionResult

    output = hybrid_result()
    output["tokens"][0].update(change)
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate(output)


def test_preview_authorization_happens_before_rendering(client, world, monkeypatch, tmp_path):
    invoice = draft(client, world)
    rendered = tmp_path / "preview.png"
    rendered.write_bytes(b"test-preview")
    calls = []

    def render(attachment, page):
        calls.append(page)
        return rendered

    monkeypatch.setattr("app.services.preview.pdf_preview", render)
    url = f"/api/v1/invoices/{invoice['id']}/preview/1"
    assert client.get(url).content == b"test-preview"
    assert calls == [1]
    assert client.get(url[:-1] + "4").status_code == 404
    login(client, world, "peer")
    assert client.get(url).status_code == 404
    assert calls == [1]
