import hashlib
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import func, select, text

from app.core.config import ROOT, get_settings
from app.models import Attachment, AuditLog, ExtractionJob, utcnow
from app.services.invoices import lock_invoice, require_invoice

EDITABLE = ("DRAFT", "CHANGES_REQUESTED")
ERRORS = {
    "TIMEOUT": "استغرقت القراءة وقتًا أطول من المسموح. أعد المحاولة أو أدخل البيانات يدويًا.",
    "INTERRUPTED": "توقفت القراءة قبل اكتمالها. يمكنك إعادة المحاولة.",
    "SOURCE_CHANGED": "الملف الأصلي غير متاح أو تغير. لم تستخدم النتيجة.",
    "PROCESS_FAILED": "تعذرت قراءة هذا المستند. جرّب صورة أوضح أو أكمل البيانات يدويًا.",
    "UNAVAILABLE": "محرك الاستخراج غير مهيأ على هذا الجهاز. يمكنك إدخال البيانات يدويًا.",
    "INVALID_RESULT": "لم ينتج الاستخراج بيانات صالحة للمراجعة. يمكنك إعادة المحاولة.",
}


def available():
    directory = ROOT / ".local/ocr-cache/official_models"
    return get_settings().extraction_python.is_file() and all(
        (directory / model / "inference.pdiparams").is_file()
        for model in ("PP-OCRv5_mobile_det", "arabic_PP-OCRv5_mobile_rec", "en_PP-OCRv5_mobile_rec")
    )


def owner(db, user, invoice_id, *, lock=False):
    invoice = (lock_invoice if lock else require_invoice)(db, user, invoice_id)
    if user.role != "EMPLOYEE" or invoice.created_by != user.id:
        raise HTTPException(403, "اقتراحات الاستخراج متاحة لصاحب الفاتورة الموظف فقط.")
    return invoice


def attachment_for(db, invoice):
    return db.scalar(select(Attachment).where(Attachment.invoice_id == invoice.id))


def source_bytes(attachment):
    directory = get_settings().upload_dir.resolve()
    path = (directory / attachment.storage_key).resolve()
    if not path.is_relative_to(directory) or not path.is_file():
        raise ValueError("SOURCE_CHANGED")
    with path.open("rb") as file:
        data = file.read(get_settings().max_upload_bytes + 1)
    if len(data) != attachment.size_bytes or hashlib.sha256(data).hexdigest() != attachment.sha256:
        raise ValueError("SOURCE_CHANGED")
    return data


def stale(job, invoice, attachment):
    return (
        invoice.status not in EDITABLE
        or job.base_revision != invoice.revision
        or attachment is None
        or job.attachment_id != attachment.id
        or job.source_sha256 != attachment.sha256
    )


def serialize(job, invoice, attachment):
    if job is None:
        return None
    is_stale = stale(job, invoice, attachment) or job.status == "STALE"
    return {
        "id": job.id,
        "status": job.status,
        "base_revision": job.base_revision,
        "language": job.language,
        "attempts": job.attempts,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
        "is_stale": is_stale,
        "error": ERRORS.get(job.error_code),
        "result": job.result if job.status == "SUCCEEDED" and not is_stale else None,
    }


def latest(db, invoice_id):
    return db.scalar(
        select(ExtractionJob)
        .where(ExtractionJob.invoice_id == invoice_id)
        .order_by(ExtractionJob.created_at.desc(), ExtractionJob.id.desc())
        .limit(1)
    )


def request_extraction(db, user, invoice_id, data):
    # Serialize each user's enqueue requests, including requests for different projects.
    lock_key = int.from_bytes(
        hashlib.sha256(f"extraction:{user.id}".encode()).digest()[:8], "big", signed=True
    )
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
    invoice = owner(db, user, invoice_id, lock=True)
    if invoice.status not in EDITABLE or invoice.revision != data.revision:
        raise HTTPException(409, "تغيرت الفاتورة أو حالتها. حدّث الصفحة قبل بدء القراءة.")
    attachment = attachment_for(db, invoice)
    previous = latest(db, invoice_id)
    if previous and previous.status in ("QUEUED", "RUNNING"):
        if stale(previous, invoice, attachment) or previous.language != data.language:
            raise HTTPException(
                409, "توجد قراءة جارية. انتظر انتهاءها ثم أعد الطلب للنسخة واللغة المطلوبة."
            )
        db.commit()
        return serialize(previous, invoice, attachment)
    if (
        previous
        and previous.status == "SUCCEEDED"
        and not stale(previous, invoice, attachment)
        and previous.language == data.language
        and not data.force
    ):
        db.commit()
        return serialize(previous, invoice, attachment)
    if not available():
        raise HTTPException(503, ERRORS["UNAVAILABLE"])
    if previous and utcnow() - previous.created_at < timedelta(seconds=10):
        raise HTTPException(429, "انتظر عشر ثوانٍ قبل إعادة طلب الاستخراج.")
    count = db.scalar(
        select(func.count())
        .select_from(ExtractionJob)
        .where(
            ExtractionJob.requested_by == user.id, ExtractionJob.status.in_(("QUEUED", "RUNNING"))
        )
    )
    if count >= 5:
        raise HTTPException(429, "لديك خمس قراءات قيد الانتظار. انتظر اكتمال إحداها.")
    try:
        source_bytes(attachment)
    except (OSError, ValueError, AttributeError):
        raise HTTPException(409, ERRORS["SOURCE_CHANGED"]) from None
    job = ExtractionJob(
        invoice_id=invoice.id,
        requested_by=user.id,
        attachment_id=attachment.id,
        source_sha256=attachment.sha256,
        base_revision=invoice.revision,
        language=data.language,
    )
    db.add(job)
    db.flush()
    db.add(
        AuditLog(
            company_id=invoice.company_id,
            invoice_id=invoice.id,
            actor_id=user.id,
            action="EXTRACTION_REQUESTED",
            details={
                "job_id": str(job.id),
                "revision": invoice.revision,
                "language": data.language,
                "force": data.force,
            },
        )
    )
    db.commit()
    return serialize(job, invoice, attachment)


def validate_review(db, user, invoice, job_id):
    job = db.scalar(
        select(ExtractionJob)
        .where(
            ExtractionJob.id == job_id,
            ExtractionJob.invoice_id == invoice.id,
            ExtractionJob.requested_by == user.id,
        )
        .with_for_update()
    )
    attachment = attachment_for(db, invoice)
    if job is None or job.status != "SUCCEEDED" or stale(job, invoice, attachment):
        raise HTTPException(
            409, "نتيجة الاستخراج غير متاحة لهذه النسخة. حدّث الفاتورة وأعد القراءة."
        )
    try:
        source_bytes(attachment)
    except (OSError, ValueError, AttributeError):
        raise HTTPException(409, ERRORS["SOURCE_CHANGED"]) from None
    return job
