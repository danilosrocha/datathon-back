"""CLI do ETL de dados externos.

uv run python -m app.etl.externo --data-dir ../ --check
uv run python -m app.etl.externo --data-dir ../
"""

import argparse
import os
import sys
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import make_url

from app.config import get_settings
from app.enrichment.externo.access import database_project_ref, resolve_access_mode
from app.enrichment.externo.access import supabase_project_ref as api_ref
from app.etl.externo.load import SourceReport, run_etl
from app.etl.externo.parse_crimes import parse_crimes_workbook
from app.etl.externo.parse_desastres import iter_zip

DISASTERS_ZIP = "registros_desastres.zip"
CRIMES_XLSX = "dados-crime-no-brasil-por-uf.xlsx"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m app.etl.externo", description=__doc__)
    p.add_argument(
        "--data-dir",
        type=Path,
        default=os.environ.get("EXTERNAL_DATA_DIR"),
        help=f"pasta com {DISASTERS_ZIP} e {CRIMES_XLSX} (ou EXTERNAL_DATA_DIR)",
    )
    p.add_argument("--disasters-zip", type=Path)
    p.add_argument("--crimes-xlsx", type=Path)
    p.add_argument("--database-url", help="padrão: DATABASE_URL")
    p.add_argument("--check", action="store_true", help="só mostra o alvo e o modo de acesso")
    p.add_argument("--dry-run", action="store_true", help="lê e valida os arquivos, sem gravar")
    return p


def _describe_target(database_url: str) -> list[str]:
    settings = get_settings()
    url = make_url(database_url)
    lines = [f"alvo do ETL: {url.host}:{url.port}/{url.database} (usuário {url.username})"]
    db_ref, project = database_project_ref(database_url), api_ref(settings.supabase_url)
    if db_ref:
        lines.append(f"o DATABASE_URL é o Postgres do projeto Supabase {db_ref}")
    elif project:
        lines.append(f"ATENÇÃO: o DATABASE_URL NÃO é o projeto Supabase {project} (SUPABASE_URL)")
    else:
        lines.append("o DATABASE_URL não é um projeto Supabase (Postgres local ou outro)")
    plan = resolve_access_mode(
        database_url=settings.database_url,
        supabase_url=settings.supabase_url,
        api_key=settings.supabase_service_role_key or settings.supabase_key,
        forced=settings.external_data_mode,
    )
    lines.append(f"modo de leitura: {plan.mode} ({plan.reason})")
    if not plan.usable:
        lines.append("  -> leitura sem privilégio: o adaptador devolverá 'fonte indisponível'")
    return lines


def _format(report: SourceReport) -> str:
    counts = " ".join(
        f"{k}={getattr(report, k)}"
        for k in ("lidas", "inseridas", "atualizadas", "inalteradas", "removidas", "rejeitadas")
    )
    return f"{report.fonte_id}: {counts} sha256={report.sha256[:12]}"


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    database_url = args.database_url or get_settings().database_url
    for line in _describe_target(database_url):
        print(line)
    if args.check:
        return 0

    disasters, crimes = args.disasters_zip, args.crimes_xlsx
    if args.data_dir:
        disasters = disasters or args.data_dir / DISASTERS_ZIP
        crimes = crimes or args.data_dir / CRIMES_XLSX
    if not (disasters or crimes):
        print("informe --data-dir (ou EXTERNAL_DATA_DIR) ou os arquivos", file=sys.stderr)
        return 2
    for path in (disasters, crimes):
        if path and not Path(path).is_file():
            print(f"arquivo não encontrado: {path}", file=sys.stderr)
            return 2

    if args.dry_run:
        if disasters:
            files = list(iter_zip(Path(disasters)))
            records = sum(len(f.registros) for f in files)
            rejected = sum(len(f.rejeicoes) for f in files)
            print(f"dry-run: {records} reconhecimentos em {len(files)} arquivos, "
                  f"{rejected} rejeitados")  # fmt: skip
        if crimes:
            parsed = parse_crimes_workbook(Path(crimes))
            print(f"dry-run: {len(parsed.registros)} registros de crime, "
                  f"{len(parsed.rejeicoes)} rejeitados")  # fmt: skip
        return 0

    engine = sa.create_engine(database_url)
    try:
        reports = run_etl(engine, disasters_zip=disasters, crimes_xlsx=crimes)
    finally:
        engine.dispose()
    for report in reports:
        print(_format(report))
        for aviso in report.avisos:
            print(f"  aviso: {aviso}")
    return 0
