"""Add submission and two-stage invoice review without changing existing drafts."""

import sqlalchemy as sa
from alembic import op

revision = "0004_invoice_workflow"
down_revision = "0937712dab68"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("invoices", sa.Column("submitted_revision", sa.Integer(), nullable=True))
    op.add_column("invoices", sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("invoices", sa.Column("project_approved_by", sa.UUID(), nullable=True))
    op.add_column("invoices", sa.Column("project_approved_revision", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_invoice_project_approver", "invoices", "users", ["project_approved_by"], ["id"]
    )
    op.drop_constraint("ck_invoice_status", "invoices", type_="check")
    op.create_check_constraint(
        "ck_invoice_status",
        "invoices",
        "status IN ('DRAFT','PROJECT_REVIEW','FINANCE_REVIEW','CHANGES_REQUESTED','APPROVED','REJECTED')",
    )
    op.create_check_constraint(
        "ck_invoice_submission",
        "invoices",
        "(status = 'DRAFT' AND submitted_revision IS NULL AND submitted_at IS NULL) OR "
        "(status <> 'DRAFT' AND submitted_revision IS NOT NULL AND submitted_at IS NOT NULL "
        "AND submitted_revision > 0 AND submitted_revision <= revision)",
    )
    op.create_check_constraint(
        "ck_invoice_project_approval",
        "invoices",
        "(status IN ('FINANCE_REVIEW','APPROVED') AND project_approved_by IS NOT NULL "
        "AND project_approved_revision IS NOT NULL AND project_approved_revision = submitted_revision) OR "
        "(status NOT IN ('FINANCE_REVIEW','APPROVED') AND project_approved_by IS NULL "
        "AND project_approved_revision IS NULL)",
    )


def downgrade():
    # Refuse to erase review history or silently convert submitted invoices into private drafts.
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM invoices WHERE status <> 'DRAFT'")):
        raise RuntimeError(
            "Cannot downgrade while submitted invoices exist. Preserve workflow history."
        )
    for name in ("ck_invoice_project_approval", "ck_invoice_submission", "ck_invoice_status"):
        op.drop_constraint(name, "invoices", type_="check")
    op.create_check_constraint("ck_invoice_status", "invoices", "status = 'DRAFT'")
    op.drop_constraint("fk_invoice_project_approver", "invoices", type_="foreignkey")
    for name in (
        "project_approved_revision",
        "project_approved_by",
        "submitted_at",
        "submitted_revision",
    ):
        op.drop_column("invoices", name)
