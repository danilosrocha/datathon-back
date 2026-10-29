"""Fixtures: banco Postgres descartável (criado e removido por sessão) e fontes sintéticas."""

import io
import os
import uuid
import zipfile
from pathlib import Path

import openpyxl
import psycopg
import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from xls_builders import layout_2003, layout_2010

ADMIN_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/postgres"
)


def _dsn(url: str) -> str:
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def pg_url():
    name = f"externo_test_{uuid.uuid4().hex[:8]}"
    try:
        admin = psycopg.connect(_dsn(ADMIN_URL), autocommit=True, connect_timeout=2)
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres indisponível para testes de integração: {exc}")
    admin.execute(f'CREATE DATABASE "{name}"')
    yield make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False)
    admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
    admin.close()


@pytest.fixture
def engine(pg_url):
    eng = sa.create_engine(pg_url)
    with eng.begin() as conn:
        conn.execute(sa.text("DROP SCHEMA IF EXISTS externo CASCADE"))
    yield eng
    eng.dispose()


AL_ROW = ["001", "AL", 2700102.0, "ÁGUA BRANCA", "-", "-", "ESTIAGEM", "SE", 702.0, 37742.0, "-",
          37799.0, "-"]  # fmt: skip
AL_ROW2 = ["002", "AL", 2700706.0, "BATALHA", "-", "-", "VENDAVAL", "SE", 855.0, 37853.0, "-",
           37855.0, "-"]  # fmt: skip
AM_ROW = ["001", 1300029.0, "ALVARÃES", 28808.0, 40007.0, "ENCHENTES", "SE", 209.0, 40281.0,
          "071", 40283.0]  # fmt: skip


def make_zip(path: Path, files: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return path


@pytest.fixture
def disasters_zip(tmp_path) -> Path:
    return make_zip(
        tmp_path / "desastres.zip",
        {
            "2003/AL.xls": layout_2003([AL_ROW, AL_ROW2], total=2),
            "2010/AM.xls": layout_2010([AM_ROW], total=1),
        },
    )


def crimes_workbook(rows) -> io.BytesIO:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "dados completos"
    ws.append(
        [
            "Estado",
            "Ano",
            "Estupro",
            "Roubos(total)",
            "Roubo em Estabelecimento Comercial ou de Serviço ",
            "População",
        ]
    )
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf


@pytest.fixture
def crimes_xlsx(tmp_path) -> Path:
    rows = [
        ["Acre", 2022, 188, 4869, None, 906876],
        ["Acre", 2023, 202, 45789, "...", 830018],
        ["Alagoas", 2023, 241, 3950, 726, 3127683],
    ]
    path = tmp_path / "crimes.xlsx"
    path.write_bytes(crimes_workbook(rows).getvalue())
    return path
