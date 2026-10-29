"""Carga idempotente dos dados externos no schema `externo`.

Cada fonte é carregada em uma única transação com UPSERT por chave natural. Reexecutar com os
mesmos arquivos não altera nenhuma linha (nem `atualizado_em`); linhas que deixaram de existir
na fonte são removidas, de modo que o banco sempre espelha o arquivo carregado.
"""

import dataclasses
import hashlib
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from app.enrichment.externo import tables as t
from app.enrichment.externo.taxonomy import UFS
from app.etl.externo.fontes import CRIMES, DESASTRES, VERSAO_ETL, FonteInfo
from app.etl.externo.parse_crimes import parse_crimes_workbook
from app.etl.externo.parse_desastres import ParsedFile, iter_zip
from app.etl.externo.quality import flag_crime_anomalies

log = logging.getLogger(__name__)

_MAX_PARAMS = 30_000  # abaixo do limite de 65.535 parâmetros do protocolo do Postgres


@dataclass
class SourceReport:
    fonte_id: str
    arquivo: str
    sha256: str
    lidas: int = 0
    inseridas: int = 0
    atualizadas: int = 0
    inalteradas: int = 0
    removidas: int = 0
    rejeitadas: int = 0
    avisos: list[str] = field(default_factory=list)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def upsert(
    conn: sa.Connection, table: sa.Table, rows: Sequence[dict], key: Sequence[str]
) -> tuple[int, int]:
    """UPSERT que só reescreve linhas cujo conteúdo mudou. Devolve (inseridas, atualizadas)."""
    if not rows:
        return 0, 0
    data_cols = [c.name for c in table.columns if c.name not in key and c.name != "atualizado_em"]
    step = max(1, _MAX_PARAMS // len(table.columns))
    inserted = updated = 0
    for start in range(0, len(rows), step):
        stmt = pg.insert(table).values(list(rows[start : start + step]))
        ex = stmt.excluded
        set_ = {c: ex[c] for c in data_cols}
        if "atualizado_em" in table.columns:
            set_["atualizado_em"] = sa.func.now()
        stmt = stmt.on_conflict_do_update(
            index_elements=list(key),
            set_=set_,
            where=sa.or_(*[table.c[c].is_distinct_from(ex[c]) for c in data_cols]),
        ).returning(sa.literal_column("(xmax = 0)").label("inserted"))
        for (was_inserted,) in conn.execute(stmt):
            inserted += was_inserted
            updated += not was_inserted
    return inserted, updated


def _write_fonte(
    conn: sa.Connection, info: FonteInfo, arquivo: str, sha: str, anos: Sequence[int]
) -> None:
    values = {
        "id": info.id,
        "nome": info.nome,
        "orgao": info.orgao,
        "granularidade": info.granularidade,
        "periodo_inicio": min(anos) if anos else None,
        "periodo_fim": max(anos) if anos else None,
        "licenca": info.licenca,
        "limitacoes": info.limitacoes,
        "url": info.url,
        "arquivo_origem": arquivo,
        "sha256": sha,
        "ultima_carga_em": datetime.now(UTC),
    }
    stmt = pg.insert(t.fonte).values(values)
    conn.execute(
        stmt.on_conflict_do_update(
            index_elements=["id"], set_={k: stmt.excluded[k] for k in values if k != "id"}
        )
    )


def _write_rejections(
    conn: sa.Connection, fonte_id: str, items: Sequence[tuple[str, int, str, list[str]]]
) -> None:
    conn.execute(sa.delete(t.etl_rejeicao).where(t.etl_rejeicao.c.fonte_id == fonte_id))
    if items:
        conn.execute(
            sa.insert(t.etl_rejeicao),
            [
                {"fonte_id": fonte_id, "arquivo": a, "linha": ln, "motivo": m, "conteudo": c}
                for a, ln, m, c in items
            ],
        )


def _coverage_rows(files: Sequence[ParsedFile]) -> list[dict]:
    anos = [f.ano for f in files]
    present = {(f.uf, f.ano): f for f in files}
    rows = []
    for uf in sorted(UFS):
        for ano in range(min(anos), max(anos) + 1):
            f = present.get((uf, ano))
            if f is None:
                rows.append(
                    {"uf": uf, "ano": ano, "arquivo_presente": False, "registros_lidos": None,
                     "total_declarado": None, "total_municipios_declarado": None,
                     "municipios_distintos": None, "divergencia_total": None}
                )  # fmt: skip
                continue
            n = len(f.registros)
            rows.append(
                {"uf": uf, "ano": ano, "arquivo_presente": True, "registros_lidos": n,
                 "total_declarado": f.total_declarado,
                 "total_municipios_declarado": f.total_municipios_declarado,
                 "municipios_distintos": len({r.cod_ibge for r in f.registros if r.cod_ibge}),
                 "divergencia_total": None if f.total_declarado is None else f.total_declarado != n}
            )  # fmt: skip
    return rows


def _load_desastres(conn: sa.Connection, path: Path, report: SourceReport) -> list[int]:
    files = list(iter_zip(path))
    if not files:
        raise ValueError(f"{path}: nenhum arquivo .xls encontrado")
    rows = [dataclasses.asdict(r) for f in files for r in f.registros]
    keys = {(r["ano"], r["uf"], r["linha_origem"]) for r in rows}
    if len(keys) != len(rows):
        raise ValueError("chave natural duplicada (ano, uf, linha_origem)")

    report.lidas = len(rows)
    report.inseridas, report.atualizadas = upsert(
        conn, t.desastre_reconhecimento, rows, ("ano", "uf", "linha_origem")
    )
    report.inalteradas = report.lidas - report.inseridas - report.atualizadas

    dr = t.desastre_reconhecimento
    names = [f.arquivo for f in files]
    removed = conn.execute(sa.delete(dr).where(~dr.c.arquivo_origem.in_(names))).rowcount
    for f in files:
        removed += conn.execute(
            sa.delete(dr).where(
                dr.c.ano == f.ano,
                dr.c.uf == f.uf,
                ~dr.c.linha_origem.in_([r.linha_origem for r in f.registros]),
            )
        ).rowcount
    report.removidas = removed

    coverage = _coverage_rows(files)
    upsert(conn, t.desastre_cobertura, coverage, ("uf", "ano"))
    anos = [f.ano for f in files]
    conn.execute(
        sa.delete(t.desastre_cobertura).where(
            sa.or_(t.desastre_cobertura.c.ano < min(anos), t.desastre_cobertura.c.ano > max(anos))
        )
    )

    rejections = [(r.arquivo, r.linha, r.motivo, r.conteudo) for f in files for r in f.rejeicoes]
    _write_rejections(conn, DESASTRES.id, rejections)
    report.rejeitadas = len(rejections)
    report.avisos += [
        f"{f.arquivo}: total declarado {f.total_declarado} != {len(f.registros)} linhas lidas"
        for f in files
        if f.total_declarado is not None and f.total_declarado != len(f.registros)
    ]
    flagged = sum(1 for r in rows if r["qa_flags"])
    if flagged:
        report.avisos.append(f"{flagged} registros carregados com qa_flags (ver coluna qa_flags)")
    return anos


def _load_crimes(conn: sa.Connection, path: Path, report: SourceReport) -> list[int]:
    parsed = parse_crimes_workbook(path)
    flag_crime_anomalies(parsed.registros)
    rows = [dataclasses.asdict(r) for r in parsed.registros]
    report.lidas = len(rows)
    report.inseridas, report.atualizadas = upsert(
        conn, t.crime_uf_indicador, rows, ("uf", "ano", "indicador")
    )
    report.inalteradas = report.lidas - report.inseridas - report.atualizadas

    c = t.crime_uf_indicador.c
    loaded = {(r["uf"], r["ano"], r["indicador"]) for r in rows}
    existing = {tuple(row) for row in conn.execute(sa.select(c.uf, c.ano, c.indicador))}
    stale = sorted(existing - loaded)
    for start in range(0, len(stale), 5000):
        report.removidas += conn.execute(
            sa.delete(t.crime_uf_indicador).where(
                sa.tuple_(c.uf, c.ano, c.indicador).in_(stale[start : start + 5000])
            )
        ).rowcount

    rejections = [(path.name, r.linha, r.motivo, r.conteudo) for r in parsed.rejeicoes]
    _write_rejections(conn, CRIMES.id, rejections)
    report.rejeitadas = len(rejections)
    flagged = sum(1 for r in rows if r["qa_flags"])
    if flagged:
        report.avisos.append(f"{flagged} valores de crime sinalizados em qa_flags (não usados)")
    if parsed.colunas_ignoradas:
        report.avisos.append(f"colunas ignoradas: {', '.join(parsed.colunas_ignoradas)}")
    return sorted({r["ano"] for r in rows})


def _run_source(engine: sa.Engine, info: FonteInfo, path: Path, loader) -> SourceReport:
    report = SourceReport(info.id, path.name, _sha256(path))
    started = datetime.now(UTC)
    try:
        with engine.begin() as conn:
            anos = loader(conn, path, report)
            _write_fonte(conn, info, path.name, report.sha256, anos)
            conn.execute(sa.insert(t.etl_execucao), [_execution_row(report, started, "ok")])
    except Exception as exc:
        with engine.begin() as conn:
            failed = SourceReport(info.id, path.name, report.sha256)
            conn.execute(
                sa.insert(t.etl_execucao), [_execution_row(failed, started, "falha", str(exc))]
            )
        raise
    return report


def _execution_row(report: SourceReport, started: datetime, status: str, msg: str | None = None):
    return {
        "fonte_id": report.fonte_id,
        "arquivo": report.arquivo,
        "sha256": report.sha256,
        "status": status,
        "iniciado_em": started,
        "finalizado_em": datetime.now(UTC),
        "lidas": report.lidas,
        "inseridas": report.inseridas,
        "atualizadas": report.atualizadas,
        "inalteradas": report.inalteradas,
        "removidas": report.removidas,
        "rejeitadas": report.rejeitadas,
        "versao_etl": VERSAO_ETL,
        "mensagem": msg or "; ".join(report.avisos) or None,
    }


def run_etl(
    engine: sa.Engine, *, disasters_zip: Path | None = None, crimes_xlsx: Path | None = None
) -> list[SourceReport]:
    """Cria o schema (se preciso) e carrega as fontes informadas."""
    t.ensure_schema(engine)
    reports = []
    if disasters_zip:
        reports.append(_run_source(engine, DESASTRES, Path(disasters_zip), _load_desastres))
    if crimes_xlsx:
        reports.append(_run_source(engine, CRIMES, Path(crimes_xlsx), _load_crimes))
    for r in reports:
        log.info("%s: %s", r.fonte_id, dataclasses.asdict(r))
    return reports
