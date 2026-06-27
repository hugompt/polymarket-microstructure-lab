"""forward paper-trading tables

Adds paper_sessions, paper_orders, paper_account_equity. Uses metadata create_all (idempotent;
only creates missing tables) to stay dialect-correct on SQLite & Postgres, consistent with 0001.

Revision ID: 0002_paper_trading
Revises: 0001_initial
Create Date: 2026-06-23
"""
from alembic import op  # noqa: F401

from app.db.base import Base
from app.db import models  # noqa: F401  register tables

revision = "0002_paper_trading"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

_PAPER_TABLES = ("paper_account_equity", "paper_orders", "paper_sessions")


def upgrade() -> None:
    bind = op.get_bind()
    # create_all only creates tables that don't already exist.
    Base.metadata.create_all(bind=bind, tables=[
        Base.metadata.tables[name] for name in _PAPER_TABLES
    ])


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind, tables=[
        Base.metadata.tables[name] for name in _PAPER_TABLES
    ])
