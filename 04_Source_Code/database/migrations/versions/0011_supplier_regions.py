"""Saudi supplier regions for explainable regional price comparison."""

import sqlalchemy as sa
from alembic import op

revision = "0011_supplier_regions"
down_revision = "0010_project_user_administration"
branch_labels = None
depends_on = None

REGIONS = (
    "RIYADH",
    "MAKKAH",
    "MADINAH",
    "QASSIM",
    "EASTERN",
    "ASIR",
    "TABUK",
    "HAIL",
    "NORTHERN_BORDERS",
    "JAZAN",
    "NAJRAN",
    "BAHAH",
    "JOUF",
)


def upgrade():
    op.add_column("suppliers", sa.Column("region_code", sa.String(30)))
    quoted = ",".join(f"'{region}'" for region in REGIONS)
    op.create_check_constraint(
        "ck_supplier_region_code", "suppliers", f"region_code IS NULL OR region_code IN ({quoted})"
    )
    op.create_index("ix_suppliers_region_code", "suppliers", ["region_code"])


def downgrade():
    op.drop_index("ix_suppliers_region_code", table_name="suppliers")
    op.drop_constraint("ck_supplier_region_code", "suppliers", type_="check")
    op.drop_column("suppliers", "region_code")
