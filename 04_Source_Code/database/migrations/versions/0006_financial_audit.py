"""Document totals and the first visible financial audit checks."""

import sqlalchemy as sa
from alembic import op

revision = "0006_financial_audit"
down_revision = "0005_extraction_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("invoices", sa.Column("document_subtotal", sa.Numeric(22, 2)))
    op.add_column("invoices", sa.Column("document_tax_total", sa.Numeric(22, 2)))
    op.add_column("invoices", sa.Column("document_grand_total", sa.Numeric(22, 2)))
    op.create_check_constraint(
        "ck_invoice_document_totals_nonnegative",
        "invoices",
        "(document_subtotal IS NULL OR document_subtotal >= 0) AND "
        "(document_tax_total IS NULL OR document_tax_total >= 0) AND "
        "(document_grand_total IS NULL OR document_grand_total >= 0)",
    )


def downgrade():
    connection = op.get_bind()
    values = connection.scalar(
        sa.text(
            "SELECT count(*) FROM invoices WHERE document_subtotal IS NOT NULL "
            "OR document_tax_total IS NOT NULL OR document_grand_total IS NOT NULL"
        )
    )
    if values:
        raise RuntimeError("Cannot discard reviewed document totals before preserving them.")
    op.drop_constraint("ck_invoice_document_totals_nonnegative", "invoices", type_="check")
    op.drop_column("invoices", "document_grand_total")
    op.drop_column("invoices", "document_tax_total")
    op.drop_column("invoices", "document_subtotal")
