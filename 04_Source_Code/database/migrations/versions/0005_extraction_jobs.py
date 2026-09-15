"""Durable, version-bound extraction suggestions."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_extraction_jobs"
down_revision = "0004_invoice_workflow"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "extraction_jobs",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("invoice_id", sa.UUID(), sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column("requested_by", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("attachment_id", sa.UUID(), sa.ForeignKey("attachments.id"), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("base_revision", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(2), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("attempt_id", sa.UUID()),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("result", postgresql.JSONB()),
        sa.Column("error_code", sa.String(40)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','STALE')",
            name="ck_extraction_status",
        ),
        sa.CheckConstraint("language IN ('ar','en')", name="ck_extraction_language"),
        sa.CheckConstraint(
            "base_revision > 0 AND attempts >= 0 AND attempts <= 2", name="ck_extraction_attempts"
        ),
    )
    op.create_index(
        "ix_extraction_invoice_created", "extraction_jobs", ["invoice_id", "created_at"]
    )
    op.create_index(
        "uq_extraction_active",
        "extraction_jobs",
        ["invoice_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('QUEUED','RUNNING')"),
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM extraction_jobs")):
        raise RuntimeError(
            "Cannot discard extraction evidence. Preserve existing jobs before downgrade."
        )
    op.drop_table("extraction_jobs")
