"""Recipient-scoped in-app workflow notifications."""

import sqlalchemy as sa
from alembic import op

revision = "0012_in_app_notifications"
down_revision = "0011_supplier_regions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notifications",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("company_id", sa.UUID(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("recipient_user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("invoice_id", sa.UUID(), sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column("project_id", sa.UUID(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.String(180), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "recipient_user_id", "dedupe_key", name="uq_notification_recipient_dedupe"
        ),
    )
    for column in ("company_id", "recipient_user_id", "invoice_id", "project_id"):
        op.create_index(f"ix_notifications_{column}", "notifications", [column])
    op.create_index(
        "ix_notification_recipient_created",
        "notifications",
        ["recipient_user_id", "created_at"],
    )


def downgrade():
    op.drop_table("notifications")
