import io

import openpyxl

from app.etl.externo.parse_crimes import parse_crimes_workbook

HEADER = ["Estado", "Ano", "Estupro", "Roubos(total)", "      Roubo de Veículo",
          "Roubo em Estabelecimento Comercial ou de Serviço ", "Homicídio Doloso ",
          "Taxa de Homicídio Doloso (por 100000)", "População"]  # fmt: skip


def workbook(rows, extra_sheets=None) -> io.BytesIO:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "dados completos"
    ws.append(HEADER)
    for row in rows:
        ws.append(row)
    for title, cells in (extra_sheets or {}).items():
        sheet = wb.create_sheet(title)
        sheet.append(cells)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def by_key(parsed):
    return {(r.uf, r.ano, r.indicador): r for r in parsed.registros}


def test_long_format_one_record_per_uf_year_indicator():
    parsed = parse_crimes_workbook(
        workbook([["Acre", 2005, 107, 37157, 640, None, 116, "=I2", 669736]])
    )
    got = by_key(parsed)
    assert got[("AC", 2005, "estupro")].valor == 107
    assert got[("AC", 2005, "roubo_total")].valor == 37157
    assert got[("AC", 2005, "populacao")].valor == 669736
    assert got[("AC", 2005, "roubo_veiculo")].valor == 640
    assert got[("AC", 2005, "homicidio_doloso")].aba_origem == "dados completos"
    assert got[("AC", 2005, "homicidio_doloso")].linha_origem == 2


def test_formula_rate_column_is_not_loaded_it_is_derived_later():
    parsed = parse_crimes_workbook(workbook([["Acre", 2005, 1, 2, 3, 4, 5, "=I2/T2", 6]]))
    assert "taxa_homicidio_doloso" not in {r.indicador for r in parsed.registros}
    assert any("Taxa de Homicídio" in c for c in parsed.colunas_ignoradas)


def test_missing_markers_keep_their_meaning_and_never_become_zero():
    parsed = parse_crimes_workbook(
        workbook([["Alagoas", 2005, "...", None, "1.914", "…", 45, 1, 3015912]])
    )
    got = by_key(parsed)
    assert (got[("AL", 2005, "estupro")].valor, got[("AL", 2005, "estupro")].situacao) == (
        None,
        "nao_disponivel",
    )
    assert got[("AL", 2005, "estupro")].valor_bruto == "..."
    assert got[("AL", 2005, "roubo_total")].situacao == "em_branco"
    assert got[("AL", 2005, "roubo_veiculo")].valor == 1914
    assert got[("AL", 2005, "roubo_estabelecimento_comercial")].situacao == "nao_disponivel"


def test_junk_rows_are_rejected_with_reason():
    parsed = parse_crimes_workbook(
        workbook([["Acre", 2005, 1, 2, 3, 4, 5, 6, 7], ["Terra do Nunca", 2005, 1, 2, 3, 4, 5, 6, 7],
                  ["Acre", 513, 1, 2, 3, 4, 5, 6, 7]])
    )  # fmt: skip
    assert {r.uf for r in parsed.registros} == {"AC"}
    assert {(r.linha, r.motivo) for r in parsed.rejeicoes} == {
        (3, "estado_desconhecido"),
        (4, "ano_invalido"),
    }


def test_sheet_notes_become_year_caveats():
    parsed = parse_crimes_workbook(
        workbook(
            [["Acre", 2020, 1, 2, 3, 4, 5, 6, 7], ["Acre", 2019, 1, 2, 3, 4, 5, 6, 7]],
            {
                "2020": [
                    "TABELA 2020 1",
                    "*Foram disponibilizado apenas os dados do 1º semestre de 2020",
                ]
            },
        )
    )
    got = by_key(parsed)
    assert "1º semestre" in got[("AC", 2020, "estupro")].ressalva
    assert got[("AC", 2019, "estupro")].ressalva is None
