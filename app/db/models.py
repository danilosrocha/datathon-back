"""Tabelas (ARQUITETURA §9). JSON vira JSONB no Postgres; os testes rodam em SQLite.

`case_events` é append-only (auditoria). `case_facts` tem PRIMARY KEY (case_id, key).
As tabelas do checkpointer do LangGraph são criadas por `AsyncPostgresSaver.setup()`."""

from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

Json = JSON().with_variant(JSONB(), "postgresql")
# BIGSERIAL no Postgres; INTEGER no SQLite (autoincremento só funciona com INTEGER PRIMARY KEY).
BigId = BigInteger().with_variant(Integer(), "sqlite")


class Base(DeclarativeBase):
    pass


class CaseRow(Base):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(32))
    channel: Mapped[str] = mapped_column(String(16))
    case_token_hash: Mapped[str] = mapped_column(String(64))
    rules_version: Mapped[str | None] = mapped_column(String(32))
    kg_version: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CaseFactRow(Base):
    __tablename__ = "case_facts"

    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), primary_key=True)
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[object] = mapped_column(Json, nullable=True)
    status: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float] = mapped_column(Float)
    evidence: Mapped[str | None] = mapped_column(Text)
    rejected_values: Mapped[list] = mapped_column(Json, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[str] = mapped_column(String(64))


class CaseEventRow(Base):
    __tablename__ = "case_events"

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(Json)
    actor: Mapped[str] = mapped_column(String(64))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RecommendationRow(Base):
    __tablename__ = "recommendations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    status: Mapped[str] = mapped_column(String(16))
    eligibility: Mapped[dict] = mapped_column(Json)
    offers: Mapped[list] = mapped_column(Json)
    trace: Mapped[dict] = mapped_column(Json)
    rules_version: Mapped[str] = mapped_column(String(32))
    kg_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KgVersionRow(Base):
    __tablename__ = "kg_versions"

    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(16))  # rascunho · publicada
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KgNodeRow(Base):
    __tablename__ = "kg_nodes"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    type: Mapped[str] = mapped_column(String(32))
    label: Mapped[str] = mapped_column(Text)
    attrs: Mapped[dict] = mapped_column(Json, default=dict)


class KgEdgeRow(Base):
    __tablename__ = "kg_edges"

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    kg_version: Mapped[int] = mapped_column(ForeignKey("kg_versions.version"), index=True)
    src: Mapped[str] = mapped_column(String(128))
    dst: Mapped[str] = mapped_column(String(128))
    type: Mapped[str] = mapped_column(String(32))
    alpha: Mapped[float | None] = mapped_column(Float)
    beta: Mapped[float | None] = mapped_column(Float)
    weight: Mapped[float | None] = mapped_column(Float)


class LearningEventRow(Base):
    """Só atividade, característica e valor confirmado — sem dados pessoais (minimização)."""

    __tablename__ = "learning_events"

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    atividade: Mapped[str] = mapped_column(String(32))
    caracteristica: Mapped[str] = mapped_column(String(64))
    valor: Mapped[bool] = mapped_column(Boolean)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApiCacheRow(Base):
    __tablename__ = "api_cache"

    key: Mapped[str] = mapped_column(String(256), primary_key=True)
    payload: Mapped[dict] = mapped_column(Json)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
