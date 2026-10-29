"""Tabelas iniciais: casos, fatos, auditoria, recomendações, context graph e cache.

Revision ID: 0001
Revises:
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "cases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("case_token_hash", sa.String(64), nullable=False),
        sa.Column("rules_version", sa.String(32)),
        sa.Column("kg_version", sa.Integer),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_table(
        "case_facts",
        sa.Column("case_id", sa.String(36), sa.ForeignKey("cases.id"), primary_key=True),
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", JSONB),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("evidence", sa.Text),
        sa.Column("rejected_values", JSONB, nullable=False, server_default="[]"),
        sa.Column("updated_at", TS, nullable=False),
        sa.Column("updated_by", sa.String(64), nullable=False),
    )
    op.create_table(
        "case_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("cases.id"), nullable=False, index=True),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("ts", TS, nullable=False),
    )
    # Auditoria append-only: o banco recusa UPDATE e DELETE em case_events.
    op.execute(
        """
        CREATE FUNCTION case_events_append_only() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'case_events é append-only'; END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER case_events_no_change BEFORE UPDATE OR DELETE ON case_events
        FOR EACH ROW EXECUTE FUNCTION case_events_append_only();
        """
    )
    op.create_table(
        "recommendations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("cases.id"), nullable=False, index=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("eligibility", JSONB, nullable=False),
        sa.Column("offers", JSONB, nullable=False),
        sa.Column("trace", JSONB, nullable=False),
        sa.Column("rules_version", sa.String(32), nullable=False),
        sa.Column("kg_version", sa.Integer, nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_table(
        "kg_versions",
        sa.Column("version", sa.Integer, primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("note", sa.Text),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_table(
        "kg_nodes",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("label", sa.Text, nullable=False),
        sa.Column("attrs", JSONB, nullable=False, server_default="{}"),
    )
    op.create_table(
        "kg_edges",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "kg_version",
            sa.Integer,
            sa.ForeignKey("kg_versions.version"),
            nullable=False,
            index=True,
        ),
        sa.Column("src", sa.String(128), nullable=False),
        sa.Column("dst", sa.String(128), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("alpha", sa.Float),
        sa.Column("beta", sa.Float),
        sa.Column("weight", sa.Float),
    )
    op.create_table(
        "learning_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("cases.id"), nullable=False, index=True),
        sa.Column("atividade", sa.String(32), nullable=False),
        sa.Column("caracteristica", sa.String(64), nullable=False),
        sa.Column("valor", sa.Boolean, nullable=False),
        sa.Column("ts", TS, nullable=False),
    )
    op.create_table(
        "api_cache",
        sa.Column("key", sa.String(256), primary_key=True),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("fetched_at", TS, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
    )
    # RLS: o front público fala só com a API; anon não lê nada.
    for table in (
        "cases", "case_facts", "case_events", "recommendations", "kg_versions", "kg_nodes",
        "kg_edges", "learning_events", "api_cache",
    ):  # fmt: skip
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in (
        "api_cache", "learning_events", "kg_edges", "kg_nodes", "kg_versions", "recommendations",
        "case_events", "case_facts", "cases",
    ):  # fmt: skip
        op.drop_table(table)
    op.execute("DROP FUNCTION IF EXISTS case_events_append_only()")
