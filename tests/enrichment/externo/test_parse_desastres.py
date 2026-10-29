import datetime as dt

import pytest
from xls_builders import layout_2003, layout_2010, layout_2016

from app.etl.externo.parse_desastres import parse_disaster_workbook

SERIAL_2003_05_01 = 37742.0  # 2003-05-01 no calendário 1900 do Excel


def test_layout_2003_with_uf_column_and_serial_dates():
    content = layout_2003(
        [
            ["001", "AL", 2700102.0, "ÁGUA BRANCA", "-", "-", "ESTIAGEM", "SE", 702.0,
             SERIAL_2003_05_01, "-", 37799.0, "-"],
        ],
        total=1,
    )  # fmt: skip
    parsed = parse_disaster_workbook(content, "2003/AL.xls")

    assert (parsed.ano, parsed.uf, parsed.total_declarado) == (2003, "AL", 1)
    assert not parsed.rejeicoes
    (rec,) = parsed.registros
    assert rec.cod_ibge == "2700102"
    assert rec.municipio == "ÁGUA BRANCA"
    assert rec.tipo_evento == "estiagem"
    assert rec.desastre_original == "ESTIAGEM"
    assert rec.se_ecp == "SE"
    assert rec.numero == 1
    assert rec.data_portaria == dt.date(2003, 5, 1)
    assert rec.data_decreto is None
    assert rec.linha_origem == 2
    assert rec.qa_flags == []


def test_layout_2010_without_uf_column_takes_uf_from_filename():
    content = layout_2010(
        [["001", 1300029.0, "ALVARÃES", 28808.0, 40007.0, "ENCHENTES", "SE", 209.0, 40281.0,
          "071", 40283.0]],
        total=1,
    )  # fmt: skip
    parsed = parse_disaster_workbook(content, "2010/AM.xls")

    (rec,) = parsed.registros
    assert (rec.ano, rec.uf, rec.cod_ibge) == (2010, "AM", "1300029")
    assert rec.tipo_evento == "inundacao"
    assert rec.linha_origem == 5
    assert parsed.total_declarado == 1


def test_layout_2016_with_blank_first_column_and_text_dates():
    content = layout_2016(
        [[1.0, "SP", 3540002.0, "Pompéia", "4734/2015", "29/12/2015",
          "TEMPESTADE LOCAL/CONVECTIVA - VENDAVAL", "SE", "049", "24/02/2016", "39",
          "26/02/2016", "ORDINÁRIO"]],
        total=1,
    )  # fmt: skip
    parsed = parse_disaster_workbook(content, "2016/SP.xls")

    (rec,) = parsed.registros
    assert rec.cod_ibge == "3540002"
    assert rec.tipo_evento == "vendaval"
    assert rec.data_decreto == dt.date(2015, 12, 29)
    assert rec.rito == "ORDINÁRIO"
    assert rec.numero_portaria == "049"
    assert parsed.total_declarado == 1


def test_invalid_ibge_is_kept_but_flagged():
    row = ["001", "AL", 2700103.0, "X", "-", "-", "SECA", "SE", "1", "-", "-", "-", "-"]
    parsed = parse_disaster_workbook(layout_2003([row]), "2003/AL.xls")
    assert parsed.registros[0].qa_flags == ["ibge_dv_invalido"]


def test_ibge_from_another_uf_is_flagged():
    row = ["001", "AL", 3550308.0, "X", "-", "-", "SECA", "SE", "1", "-", "-", "-", "-"]
    parsed = parse_disaster_workbook(layout_2003([row]), "2003/AL.xls")
    assert "ibge_uf_diverge_arquivo" in parsed.registros[0].qa_flags


def test_row_without_municipality_is_rejected_not_dropped_silently():
    ok = ["001", "AL", 2700102.0, "ÁGUA BRANCA", "-", "-", "SECA", "SE", "1", "-", "-", "-", "-"]
    note = ["¹ Nota de rodapé qualquer"]
    parsed = parse_disaster_workbook(layout_2003([ok, note], total=1), "2003/AL.xls")
    assert len(parsed.registros) == 1
    assert [r.motivo for r in parsed.rejeicoes] == ["linha_sem_municipio"]
    assert parsed.rejeicoes[0].linha == 3


def test_blank_rows_are_ignored_and_total_row_stops_parsing():
    ok = ["001", "AL", 2700102.0, "ÁGUA BRANCA", "-", "-", "SECA", "SE", "1", "-", "-", "-", "-"]
    parsed = parse_disaster_workbook(layout_2003([ok, [""] * 13], total=1), "2003/AL.xls")
    assert len(parsed.registros) == 1
    assert not parsed.rejeicoes


def test_workbook_without_header_raises():
    from xls_builders import _workbook

    from app.etl.externo.parse_desastres import LayoutDesconhecido

    with pytest.raises(LayoutDesconhecido):
        parse_disaster_workbook(_workbook([["nada", "aqui"]]), "2003/AL.xls")


def test_bad_filename_raises():
    from app.etl.externo.parse_desastres import LayoutDesconhecido

    with pytest.raises(LayoutDesconhecido):
        parse_disaster_workbook(layout_2003([]), "AL.xls")


def test_two_total_rows_are_told_apart_by_label():
    from xls_builders import _workbook

    header = ["Nº", "UF", "Código IBGE ", "Município", "Nº do Decreto", "Data do Decreto",
              "Desastre", "SE/ECP", "Nº da Portaria", "Data da Portaria", "Nº do D.O.U.",
              "Data do D.O.U.", "Rito"]  # fmt: skip
    row = ["001", "AL", 2700102.0, "ÁGUA BRANCA", "-", "-", "SECA", "SE", "1", "-", "-", "-", "-"]
    content = _workbook([
        header, row, [""],
        ["Total de municípios reconhecidos:", "041"],
        [""],
        ["Total de reconhecimentos realizados:", "115"],
    ])  # fmt: skip
    parsed = parse_disaster_workbook(content, "2003/AL.xls")
    assert parsed.total_declarado == 115
    assert parsed.total_municipios_declarado == 41
    assert len(parsed.registros) == 1
    assert not parsed.rejeicoes
