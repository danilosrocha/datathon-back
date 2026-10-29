"""Gera data/risco_municipio.csv: nível de risco regional por município (sempre `estimado`).

Fontes (pasta de contexto do desafio):
- Atlas Digital de Desastres no Brasil (MIDR/Defesa Civil, S2iD): reconhecimentos de SE/ECP por
  município, 2003–2016 (`registros_desastres.zip`, uma planilha por ano e UF).
- Dados de criminalidade por UF (`dados-crime-no-brasil-por-uf.xlsx`): roubos totais e população.

Método (premissas da equipe, documentar no README):
- vendaval/granizo/alagamento: nº de reconhecimentos da tipologia no período →
  0 = baixo, 1–2 = médio, ≥ 3 = alto. Subnotificação: ausência de registro ≠ ausência de risco,
  por isso a confiança é baixa.
- roubo: mediana 2018–2023 de roubos por 100 mil hab. na UF → tercis entre UFs. Nível UF, não
  município: confiança baixa.

Uso: uv run python -m app.enrichment.risco_municipio --contexto ../xenga-datathon-context \
        --base <pasta com enderecos_estabelecimentos.csv> --out data/risco_municipio.csv
"""

import argparse
import io
import re
import unicodedata
import zipfile
from pathlib import Path

import pandas as pd

TIPOLOGIAS = {
    "vendaval": re.compile(r"VENDAVAL|CICLONE|TORNADO"),
    "granizo": re.compile(r"GRANIZO"),
    "alagamento": re.compile(r"ALAGAMENTO|INUNDA|ENXURRADA|ENCHENTE"),
}
UFS = {
    "acre": "AC", "alagoas": "AL", "amapa": "AP", "amazonas": "AM", "bahia": "BA", "ceara": "CE",
    "distrito federal": "DF", "espirito santo": "ES", "goias": "GO", "maranhao": "MA",
    "mato grosso": "MT", "mato grosso do sul": "MS", "minas gerais": "MG", "para": "PA",
    "paraiba": "PB", "parana": "PR", "pernambuco": "PE", "piaui": "PI", "rio de janeiro": "RJ",
    "rio grande do norte": "RN", "rio grande do sul": "RS", "rondonia": "RO", "roraima": "RR",
    "santa catarina": "SC", "sao paulo": "SP", "sergipe": "SE", "tocantins": "TO",
}  # fmt: skip


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().strip().lower()


def disaster_counts(zip_path: Path) -> pd.DataFrame:
    """Contagem de reconhecimentos por município e tipologia."""
    rows = []
    with zipfile.ZipFile(zip_path) as zf:
        for name in sorted(n for n in zf.namelist() if n.endswith(".xls")):
            sheet = pd.read_excel(io.BytesIO(zf.read(name)), header=None, engine="xlrd")
            # Cabeçalho varia por ano: "Código IBGE"/"Cód. IBGE" e "Desastre"/"Evento".
            labels = sheet.map(lambda v: _plain(str(v)))
            header = labels.index[labels.apply(lambda r: r.str.contains("ibge").any(), axis=1)]
            if header.empty:
                continue
            row = labels.loc[header[0]]
            ibge = row[row.str.contains("ibge")].index[0]
            event = row[row.isin(["desastre", "evento"])].index[0]
            for code, what in (
                sheet.iloc[header[0] + 1 :, [ibge, event]].dropna().itertuples(index=False)
            ):
                digits = re.sub(r"\D", "", str(code))[:7]
                if len(digits) == 7:
                    rows.append((digits, str(what).upper()))
    events = pd.DataFrame(rows, columns=["municipio_ibge", "desastre"])
    for kind, pattern in TIPOLOGIAS.items():
        events[kind] = events["desastre"].str.contains(pattern)
    return events.groupby("municipio_ibge")[list(TIPOLOGIAS)].sum()


def robbery_levels(xlsx_path: Path) -> dict[str, str]:
    df = pd.read_excel(xlsx_path)
    df = df[df["Ano"].between(2018, 2023)].copy()
    df["uf"] = df["Estado"].map(lambda s: UFS[_plain(s)])
    df["taxa"] = df["Roubos(total)"] / df["População"] * 100_000
    rate = df.groupby("uf")["taxa"].median()
    tercis = rate.quantile([1 / 3, 2 / 3])
    return {
        uf: "baixo" if v <= tercis.iloc[0] else "medio" if v <= tercis.iloc[1] else "alto"
        for uf, v in rate.items()
    }


def level(count: int) -> str:
    return "baixo" if count == 0 else "medio" if count <= 2 else "alto"


# Código IBGE: os 2 primeiros dígitos identificam a UF.
UF_CODES = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
    "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL",
    "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR",
    "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF",
}  # fmt: skip


def build(contexto: Path, base: Path, out: Path) -> pd.DataFrame:
    """Municípios da base + todos com registro no Atlas (para a jornada web). Município fora da
    tabela fica sem fato de risco climático (desconhecido), só com o roubo da UF."""
    counts = disaster_counts(contexto / "registros_desastres.zip")
    robbery = robbery_levels(contexto / "dados-crime-no-brasil-por-uf.xlsx")
    places = pd.read_csv(base / "enderecos_estabelecimentos.csv", encoding="utf-8-sig", dtype=str)
    places = places[["codigo_ibge_municipio", "uf_real"]].rename(
        columns={"codigo_ibge_municipio": "municipio_ibge", "uf_real": "uf"}
    )
    atlas = pd.DataFrame({"municipio_ibge": counts.index})
    atlas["uf"] = atlas["municipio_ibge"].str[:2].map(UF_CODES)
    places = (
        pd.concat([places, atlas.dropna()])
        .drop_duplicates("municipio_ibge")
        .sort_values("municipio_ibge")
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(sorted(robbery.items()), columns=["uf", "risco_roubo_regiao"]).to_csv(
        out.parent / "risco_uf.csv", index=False
    )
    rows = []
    for m, uf in places.itertuples(index=False):
        c = counts.loc[m] if m in counts.index else {k: 0 for k in TIPOLOGIAS}
        rows.append(
            {
                "municipio_ibge": m,
                "uf": uf,
                **{f"risco_{k}_regiao": level(int(c[k])) for k in TIPOLOGIAS},
                "risco_roubo_regiao": robbery.get(uf),
                **{f"registros_{k}_2003_2016": int(c[k]) for k in TIPOLOGIAS},
            }
        )
    table = pd.DataFrame(rows)
    table.to_csv(out, index=False)
    return table


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--contexto", type=Path, required=True)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("data/risco_municipio.csv"))
    args = parser.parse_args()
    table = build(args.contexto, args.base, args.out)
    print(f"{len(table)} municípios → {args.out}")


if __name__ == "__main__":
    main()
