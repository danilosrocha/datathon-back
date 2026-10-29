"""Constrói planilhas .xls sintéticas com os mesmos layouts dos arquivos reais."""

import io

import xlwt


def _workbook(rows: list[list]) -> bytes:
    wb = xlwt.Workbook()
    ws = wb.add_sheet("Plan1")
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            if value is not None:
                ws.write(r, c, value)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# Layout 2003: cabeçalho na linha 0, coluna UF, datas como número serial do Excel.
def layout_2003(rows: list[list], total: int | None = None) -> bytes:
    header = ["Nº", "UF", "Código IBGE ", "Município", "Nº do Decreto", "Data do Decreto",
              "Desastre", "SE/ECP", "Nº da Portaria", "Data da Portaria", "Nº do D.O.U.",
              "Data do D.O.U.", "Rito"]  # fmt: skip
    body = [list(r) for r in rows]
    if total is not None:
        body.append(["Total de reconhecimentos realizados:", "", "", "", str(total)])
    return _workbook([header, *body])


# Layout 2010: três linhas de título, sem coluna UF, "Evento", total no rodapé.
def layout_2010(rows: list[list], total: int | None = None) -> bytes:
    header = ["Nº", "Cód. IBGE", "Município", "Nº do Decreto", "Data do Decreto", "Evento",
              "SE/ECP", "Nº da Portaria", "Data da Portaria", "Nº do DOU", "Data do DOU"]  # fmt: skip
    body = [list(r) for r in rows]
    if total is not None:
        body.append(["Total de reconhecimentos realizados: ", "", "", "", str(total)])
    return _workbook([["Secretaria Nacional de Defesa Civil"], ["Reconhecimentos - AMAZONAS"],
                      ["Ano: 2010"], header, *body])  # fmt: skip


# Layout 2016: seis linhas de título, coluna A vazia, datas em texto dd/mm/aaaa.
def layout_2016(rows: list[list], total: int | None = None) -> bytes:
    header = ["", "Nº", "UF", "Código IBGE", "Município", "Nº do Decreto", "Data do Decreto",
              "Desastre", "SE/ECP", "Nº da Portaria", "Data da Portaria", "Nº do D.O.U.",
              "Data do D.O.U.", "Rito"]  # fmt: skip
    body = [["", *r] for r in rows]
    if total is not None:
        body.append(["", "Total de reconhecimentos realizados: ", "", "", "", float(total)])
    titles = [[""], ["", "Ministério da Integração Nacional"], ["", "Secretaria Nacional"],
              ["", "Reconhecimentos realizados entre 01/01/2016 e 31/12/2016 - SAO PAULO"],
              [""]]  # fmt: skip
    return _workbook([*titles, header, *body])
