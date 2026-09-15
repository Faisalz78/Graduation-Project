import os

from alembic import context
from dotenv import dotenv_values
from sqlalchemy import create_engine, pool

from app import models  # noqa: F401 - registers every table with Alembic metadata.
from app.core.config import ROOT
from app.core.database import Base

values = dotenv_values(ROOT / ".env")
url = os.environ.get("MIGRATION_DATABASE_URL") or values["MIGRATION_DATABASE_URL"]

if context.is_offline_mode():
    context.configure(
        url=url,
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
