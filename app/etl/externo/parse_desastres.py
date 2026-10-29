"""Leitura dos .xls de reconhecimentos de desastres (um arquivo por ano e UF).

Os arquivos mudam de layout ao longo dos anos (linhas de título, coluna UF, rótulo
"Desastre"/"Evento", datas em serial do Excel ou texto). O parser localiza o cabeçalho
pelo conteúdo e mapeia as colunas pelo nome, nunca pela posição.
"""

import datetime as dt
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import xlrd

from app.enrichment.externo.taxonomy import (
    UFS,
    clean_label,
    fold,
    is_valid_ibge,
    normalize_tipo_evento,
    parse_br_int,
    uf_from_ibge,
)

_FILENAME = re.compile(r"(?:^|/)(\d{4})/([A-Za-z]{2})\.xls$")
_DATE_TEXT = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
_HEADER_SCAN_ROWS = 15

# nome do campo -> cabeçalhos aceitos (já sem acento/maiúsculas)
_COLUMNS = {
    "numero": {"no", "n"},
    "uf": {"uf"},
    "cod_ibge": {"codigo ibge", "cod. ibge", "cod ibge"},
    "municipio": {"municipio"},
    "numero_decreto": {"no do decreto"},
    "data_decreto": {"data do decreto"},
    "desastre": {"desastre", "evento"},
    "se_ecp": {"se/ecp"},
    "numero_portaria": {"no da portaria"},
    "data_portaria": {"data da portaria"},
    "numero_dou": {"no do d.o.u.", "no do dou"},
    "data_dou": {"data do d.o.u.", "data do dou"},
    "rito": {"rito"},
}
_DATE_FIELDS = ("data_decreto", "data_portaria", "data_dou")


class LayoutDesconhecido(ValueError):
    """Arquivo fora do padrão esperado (nome, cabeçalho ou planilha)."""


@dataclass
class DisasterRecord:
    ano: int
    uf: str
    linha_origem: int
    numero: int | None
    cod_ibge: str | None
    municipio: str
    desastre_original: str
    tipo_evento: str
    se_ecp: str | None
    numero_decreto: str | None
    data_decreto: dt.date | None
    numero_portaria: str | None
    data_portaria: dt.date | None
    numero_dou: str | None
    data_dou: dt.date | None
    rito: str | None
    arquivo_origem: str
    qa_flags: list[str] = field(default_factory=list)


@dataclass
class Rejection:
    arquivo: str
    linha: int
    motivo: str
    conteudo: list[str]


@dataclass
class ParsedFile:
    arquivo: str
    ano: int
    uf: str
    registros: list[DisasterRecord]
    rejeicoes: list[Rejection]
    total_declarado: int | None
    total_municipios_declarado: int | None = None


def _text(value: object) -> str | None:
    if isinstance(value, float):
        value = int(value) if value.is_integer() else value
    text = str(value).strip()
    return None if text in {"", "-"} else text


def _find_header(sheet: xlrd.sheet.Sheet) -> tuple[int, dict[str, int]] | None:
    for r in range(min(_HEADER_SCAN_ROWS, sheet.nrows)):
        folded = [fold(sheet.cell_value(r, c)) for c in range(sheet.ncols)]
        if "municipio" not in folded:
            continue
        mapping: dict[str, int] = {}
        for c, name in enumerate(folded):
            for field_name, accepted in _COLUMNS.items():
                if field_name not in mapping and name in accepted:
                    mapping[field_name] = c
            if "se/ecp" not in mapping and name.startswith("situacao de emergencia"):
                mapping["se_ecp"] = c
        return r, mapping
    return None


def _date(value: object, datemode: int) -> tuple[dt.date | None, bool]:
    """Devolve (data, inválida). Vazio ou "-" não é inválido."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        try:
            return xlrd.xldate_as_datetime(value, datemode).date(), False
        except (xlrd.xldate.XLDateError, OverflowError, ValueError):
            return None, True
    text = _text(value)
    if text is None:
        return None, False
    match = _DATE_TEXT.fullmatch(text)
    if match:
        day, month, year = map(int, match.groups())
        try:
            return dt.date(year, month, day), False
        except ValueError:
            return None, True
    return None, True


def _declared_total(row: list[object]) -> int | None:
    for value in row[1:]:
        number, situacao = parse_br_int(value if not isinstance(value, str) else value.strip())
        if situacao == "informado":
            return number
    return None


def _ibge(value: object) -> tuple[str | None, list[str]]:
    text = _text(value)
    if text is None:
        return None, ["ibge_ausente"]
    if not re.fullmatch(r"\d{7}", text):
        return None, ["ibge_formato_invalido"]
    return text, [] if is_valid_ibge(text) else ["ibge_dv_invalido"]


def parse_disaster_workbook(content: bytes, arquivo: str) -> ParsedFile:
    match = _FILENAME.search(arquivo)
    if not match or match.group(2).upper() not in UFS:
        raise LayoutDesconhecido(f"{arquivo}: esperado '<ano>/<UF>.xls'")
    ano, file_uf = int(match.group(1)), match.group(2).upper()

    book = xlrd.open_workbook(file_contents=content)
    found = None
    for sheet in book.sheets():
        found = _find_header(sheet) if sheet.nrows else None
        if found:
            break
    if not found:
        raise LayoutDesconhecido(f"{arquivo}: cabeçalho com 'Município' não encontrado")
    header_row, cols = found
    if not {"cod_ibge", "municipio", "desastre"} <= cols.keys():
        raise LayoutDesconhecido(f"{arquivo}: colunas obrigatórias ausentes ({sorted(cols)})")

    def cell(row: list[object], name: str) -> object:
        index = cols.get(name)
        return row[index] if index is not None else ""

    registros: list[DisasterRecord] = []
    rejeicoes: list[Rejection] = []
    total: int | None = None
    total_municipios: int | None = None
    seen_total = False

    for r in range(header_row + 1, sheet.nrows):
        row = [sheet.cell_value(r, c) for c in range(sheet.ncols)]
        texts = [_text(v) or "" for v in row]
        if not any(texts):
            continue
        label = next((v for v in texts[:3] if fold(v).startswith("total de")), None)
        if label is not None:
            seen_total = True
            first = next(i for i, v in enumerate(texts[:3]) if v == label)
            if fold(label).startswith("total de municipios"):
                total_municipios = _declared_total(row[first:])
            else:
                total = _declared_total(row[first:])
            continue
        linha = r + 1
        if seen_total:
            rejeicoes.append(Rejection(arquivo, linha, "linha_apos_total", texts))
            continue
        municipio = _text(cell(row, "municipio"))
        if municipio is None:
            rejeicoes.append(Rejection(arquivo, linha, "linha_sem_municipio", texts))
            continue

        flags: list[str] = []
        cod_ibge, ibge_flags = _ibge(cell(row, "cod_ibge"))
        flags += ibge_flags
        if cod_ibge and uf_from_ibge(cod_ibge) != file_uf:
            flags.append("ibge_uf_diverge_arquivo")
        uf_col = _text(cell(row, "uf"))
        if uf_col and uf_col.upper() != file_uf:
            flags.append("uf_coluna_diverge_arquivo")

        dates: dict[str, dt.date | None] = {}
        for name in _DATE_FIELDS:
            dates[name], invalid = _date(cell(row, name), book.datemode)
            if invalid:
                flags.append(f"{name}_invalida")

        se_ecp = _text(cell(row, "se_ecp"))
        if se_ecp is not None:
            se_ecp = se_ecp.upper()
            if se_ecp not in {"SE", "ECP"}:
                flags.append("se_ecp_invalido")
                se_ecp = None

        desastre = clean_label(_text(cell(row, "desastre")) or "")
        registros.append(
            DisasterRecord(
                ano=ano,
                uf=file_uf,
                linha_origem=linha,
                numero=parse_br_int(_text(cell(row, "numero")))[0],
                cod_ibge=cod_ibge,
                municipio=municipio,
                desastre_original=desastre,
                tipo_evento=normalize_tipo_evento(desastre),
                se_ecp=se_ecp,
                numero_decreto=_text(cell(row, "numero_decreto")),
                data_decreto=dates["data_decreto"],
                numero_portaria=_text(cell(row, "numero_portaria")),
                data_portaria=dates["data_portaria"],
                numero_dou=_text(cell(row, "numero_dou")),
                data_dou=dates["data_dou"],
                rito=_text(cell(row, "rito")),
                arquivo_origem=arquivo,
                qa_flags=flags,
            )
        )

    return ParsedFile(arquivo, ano, file_uf, registros, rejeicoes, total, total_municipios)


def iter_zip(path: Path) -> Iterator[ParsedFile]:
    """Lê todos os `<ano>/<UF>.xls` do zip, em ordem estável."""
    with zipfile.ZipFile(path) as zf:
        for name in sorted(n for n in zf.namelist() if n.lower().endswith(".xls")):
            yield parse_disaster_workbook(zf.read(name), name)
