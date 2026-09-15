"""Durable PostgreSQL queue; each OCR attempt runs in a bounded child process."""

import json
import logging
import subprocess
import time
import uuid
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import or_, select

from app.core.config import ROOT, get_settings
from app.core.database import SessionLocal
from app.models import Attachment, ExtractionJob, User, utcnow
from app.schemas.extraction import ExtractionResult
from app.services.extraction import attachment_for, owner, source_bytes, stale
from app.services.processes import run_bounded

log = logging.getLogger(__name__)


def claim(db):
    now = utcnow()
    job = db.scalar(
        select(ExtractionJob)
        .where(
            or_(
                ExtractionJob.status == "QUEUED",
                (ExtractionJob.status == "RUNNING") & (ExtractionJob.lease_until < now),
            )
        )
        .order_by(ExtractionJob.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        db.rollback()
        return None
    if job.attempts >= 2:
        job.status, job.error_code, job.finished_at = "FAILED", "INTERRUPTED", now
        job.lease_until = None
        db.commit()
        return None
    job.status = "RUNNING"
    job.attempts += 1
    job.attempt_id = uuid.uuid4()
    job.lease_until = now + timedelta(seconds=get_settings().extraction_timeout_seconds + 60)
    db.commit()
    return job.id, job.attempt_id


def run_document(data, media_type, language):
    settings = get_settings()
    if not settings.extraction_python.is_file():
        raise ValueError("UNAVAILABLE")
    directory = (ROOT / ".local/extraction-runs").resolve()
    directory.mkdir(parents=True, exist_ok=True)
    identifier = uuid.uuid4().hex
    suffix = {
        "application/pdf": ".pdf",
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "application/xml": ".xml",
    }[media_type]
    source = directory / (identifier + suffix)
    output = directory / (identifier + ".json")
    try:
        source.write_bytes(data)
        returncode = run_bounded(
            [
                str(settings.extraction_python),
                "-X",
                "utf8",
                str(ROOT / "04_Source_Code/ai/document_intelligence/run_extraction.py"),
                "--input",
                str(source),
                "--output",
                str(output),
                "--language",
                language,
            ],
            timeout=settings.extraction_timeout_seconds,
        )
        if returncode:
            raise ValueError("PROCESS_FAILED")
        if not output.is_file() or output.stat().st_size > 2_000_000:
            raise ValueError("INVALID_RESULT")
        try:
            result = ExtractionResult.model_validate_json(output.read_bytes()).model_dump()
            if len(json.dumps(result, ensure_ascii=False).encode()) > 1_500_000:
                raise ValueError("Result too large")
            return result
        except (ValueError, TypeError):
            raise ValueError("INVALID_RESULT") from None
    finally:
        source.unlink(missing_ok=True)
        output.unlink(missing_ok=True)


def authorized_invoice(db, job):
    user = db.get(User, job.requested_by)
    if user is None or not user.is_active:
        return None
    try:
        invoice = owner(db, user, job.invoice_id, lock=True)
        return None if stale(job, invoice, attachment_for(db, invoice)) else invoice
    except HTTPException:
        return None


def process(job_id, attempt_id, *, session_factory=SessionLocal, runner=run_document):
    result, error = None, None
    with session_factory() as db:
        job = db.get(ExtractionJob, job_id)
        if not job or job.attempt_id != attempt_id or job.status != "RUNNING":
            return
        invoice = authorized_invoice(db, job)
        if invoice is None:
            error = "STALE"
        else:
            attachment = db.get(Attachment, job.attachment_id)
            try:
                data = source_bytes(attachment)
            except (OSError, ValueError):
                error = "SOURCE_CHANGED"
            media, language = attachment.media_type, job.language
        db.rollback()  # Release invoice/project locks before the slow OCR process.
    if error is None:
        try:
            result = runner(data, media, language)
            result = ExtractionResult.model_validate(result).model_dump()
        except subprocess.TimeoutExpired:
            error = "TIMEOUT"
        except ValueError as failure:
            error = (
                str(failure)
                if str(failure)
                in ("SOURCE_CHANGED", "UNAVAILABLE", "PROCESS_FAILED", "INVALID_RESULT")
                else "INVALID_RESULT"
            )
        except Exception:
            error = "PROCESS_FAILED"
    with session_factory() as db:
        job = db.get(ExtractionJob, job_id)
        if not job:
            return
        invoice = authorized_invoice(db, job)
        # Invoice/project locks precede job locks, like the request and review endpoints.
        job = db.scalar(
            select(ExtractionJob)
            .where(ExtractionJob.id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if job.status != "RUNNING" or job.attempt_id != attempt_id:
            db.rollback()
            return  # A timed-out lease was claimed by another attempt.
        if invoice is None or error == "STALE":
            job.status, job.result, job.error_code = "STALE", None, None
        else:
            try:
                source_bytes(db.get(Attachment, job.attachment_id))
            except (OSError, ValueError):
                error = "SOURCE_CHANGED"
            job.status = "FAILED" if error else "SUCCEEDED"
            job.result = None if error else result
            job.error_code = error
        job.finished_at, job.lease_until = utcnow(), None
        db.commit()


def main():
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            with SessionLocal() as db:
                work = claim(db)
            if work:
                process(*work)
            else:
                time.sleep(2)
        except KeyboardInterrupt:
            return
        except Exception as failure:
            # Do not log database connection strings or OCR document contents.
            log.error("Extraction worker retrying after %s", type(failure).__name__)
            time.sleep(5)


if __name__ == "__main__":
    main()
