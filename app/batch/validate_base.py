"""Validação do formato da base comum antes do lote ou do treino do context graph.

Confere arquivos, colunas usadas pelo loader, chaves únicas, integridade entre tabelas, domínios
das categorias e faixas numéricas. Erro = o loader não consegue usar a base; aviso = dado
utilizável que pede atenção (ex.: área zerada, CNAE fora do formato).

Uso: uv run python -m app.batch.validate_base --input data/Seguro_Empresarial_Desenvolvimento
"""

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

REQUIRED = {
    "empresas.csv": [
        "empresa_id",
        "grupo_atividade",
        "cnae_principal",
        "porte",
        "faturamento_mensal",
        "origem_faturamento",
        "confianca_faturamento",
        "quantidade_funcionarios_estimada",
        "dependencia_digital_pct",
        "percentual_vendas_online_estimado",
        "percentual_receita_delivery_est",
    ],
    "enderecos_estabelecimentos.csv": [
        "imovel_id",
        "empresa_id",
        "uf_real",
        "codigo_ibge_municipio",
        "possui_termo_loja",
        "possui_termo_sala",
        "possui_termo_galeria",
        "possui_termo_torre",
        "area_cadastrada_m2",
        "origem_area",
        "confianca_area",
        "padrao_construtivo_cadastrado",
        "material_parede_externa_cadastrado",
        "situacao_imovel_cadastral",
    ],
    "sinais_financeiros_operacionais.csv": [
        "imovel_id",
        "empresa_id",
        "pagamento_aluguel_recorrente",
        "valor_aluguel_recorrente",
        "despesa_fixa_mensal_estimada",
        "estoque_medio_estimado",
        "probabilidade_refrigeracao_referencia",
        "probabilidade_delivery_referencia",
        "percentual_recebimentos_digitais",
        "probabilidade_tratamento_dados",
        "indice_exposicao_digital",
    ],
    "bens_cadastrados.csv": [
        "bem_id",
        "empresa_id",
        "imovel_id_referencia",
        "tipo_bem",
        "nivel_confianca_vinculo",
        "valor_bem_ponderado_referencia",
    ],
    "template_resultado_times.csv": ["empresa_id", "imovel_id"],
    "template_coberturas_times.csv": [],
}
DOMAINS = {
    ("empresas.csv", "origem_faturamento"): {"INFORMADO", "PRESUMIDO_COM_BASE_EM_GASTOS"},
    ("empresas.csv", "confianca_faturamento"): {"ALTA", "MEDIA", "BAIXA"},
    ("enderecos_estabelecimentos.csv", "confianca_area"): {"ALTA", "MEDIA", "BAIXA"},
    ("enderecos_estabelecimentos.csv", "situacao_imovel_cadastral"): {
        "REGULAR",
        "EM_OBRA",
        "IRREGULAR",
    },
    ("enderecos_estabelecimentos.csv", "padrao_construtivo_cadastrado"): {
        "ECONOMICO",
        "NORMAL",
        "SUPERIOR",
        "NAO_DISPONIVEL",
    },
    ("enderecos_estabelecimentos.csv", "material_parede_externa_cadastrado"): {
        "ALVENARIA",
        "CONCRETO",
        "NAO_DISPONIVEL",
    },
    ("enderecos_estabelecimentos.csv", "possui_termo_loja"): {"SIM", "NAO"},
    ("sinais_financeiros_operacionais.csv", "pagamento_aluguel_recorrente"): {"SIM", "NAO"},
    ("bens_cadastrados.csv", "nivel_confianca_vinculo"): {"ALTA", "MEDIA", "BAIXA"},
}
PROBABILITIES = [
    ("sinais_financeiros_operacionais.csv", c)
    for c in (
        "probabilidade_refrigeracao_referencia",
        "probabilidade_delivery_referencia",
        "percentual_recebimentos_digitais",
        "probabilidade_tratamento_dados",
    )
] + [
    ("empresas.csv", "percentual_vendas_online_estimado"),
    ("empresas.csv", "percentual_receita_delivery_est"),
]
NON_NEGATIVE = [
    ("empresas.csv", "faturamento_mensal"),
    ("empresas.csv", "quantidade_funcionarios_estimada"),
    ("enderecos_estabelecimentos.csv", "area_cadastrada_m2"),
    ("sinais_financeiros_operacionais.csv", "valor_aluguel_recorrente"),
    ("sinais_financeiros_operacionais.csv", "despesa_fixa_mensal_estimada"),
    ("sinais_financeiros_operacionais.csv", "estoque_medio_estimado"),
    ("bens_cadastrados.csv", "valor_bem_ponderado_referencia"),
]
CNAE = re.compile(r"^\d{4}-\d/\d{2}$")
IBGE = re.compile(r"^\d{7}$")


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate(base: Path) -> Report:
    report = Report()
    tables: dict[str, pd.DataFrame] = {}
    for name, columns in REQUIRED.items():
        path = base / name
        if not path.exists():
            report.errors.append(f"{name}: arquivo ausente")
            continue
        df = pd.read_csv(path, encoding="utf-8-sig", dtype={"codigo_ibge_municipio": str})
        missing = [c for c in columns if c not in df.columns]
        if missing:
            report.errors.append(f"{name}: colunas ausentes {missing}")
        tables[name] = df
        report.stats[name] = len(df)
    if report.errors:
        return report

    emp, imo = tables["empresas.csv"], tables["enderecos_estabelecimentos.csv"]
    sig, bens = tables["sinais_financeiros_operacionais.csv"], tables["bens_cadastrados.csv"]
    tpl = tables["template_resultado_times.csv"]

    for name, key in (
        ("empresas.csv", "empresa_id"),
        ("enderecos_estabelecimentos.csv", "imovel_id"),
        ("sinais_financeiros_operacionais.csv", "imovel_id"),
        ("bens_cadastrados.csv", "bem_id"),
    ):
        dup = tables[name][key].duplicated().sum()
        if dup:
            report.errors.append(f"{name}: {dup} valores repetidos em {key}")

    pairs = set(zip(tpl["empresa_id"], tpl["imovel_id"], strict=True))
    if len(pairs) != len(tpl):
        report.errors.append("template_resultado_times.csv: pares empresa+imóvel repetidos")
    for missing_name, ids, source in (
        ("empresas.csv", set(tpl["empresa_id"]) - set(emp["empresa_id"]), "empresa_id"),
        (
            "enderecos_estabelecimentos.csv",
            set(tpl["imovel_id"]) - set(imo["imovel_id"]),
            "imovel_id",
        ),
        (
            "sinais_financeiros_operacionais.csv",
            set(tpl["imovel_id"]) - set(sig["imovel_id"]),
            "imovel_id",
        ),
    ):
        if ids:
            report.errors.append(f"{missing_name}: {len(ids)} {source} do template sem registro")
    orphans = set(bens["imovel_id_referencia"]) - set(imo["imovel_id"])
    if orphans:
        report.warnings.append(
            f"bens_cadastrados.csv: {len(orphans)} imóveis de referência inexistentes"
        )

    for (name, column), allowed in DOMAINS.items():
        bad = set(tables[name][column].dropna().astype(str)) - allowed
        if bad:
            report.errors.append(f"{name}.{column}: valores fora do domínio {sorted(bad)}")
    for name, column in PROBABILITIES:
        values = tables[name][column]
        out = ((values < 0) | (values > 1)).sum() + values.isna().sum()
        if out:
            report.errors.append(f"{name}.{column}: {out} valores fora de 0–1 ou vazios")
    for name, column in NON_NEGATIVE:
        values = tables[name][column]
        bad = (values < 0).sum() + values.isna().sum()
        if bad:
            report.errors.append(f"{name}.{column}: {bad} valores negativos ou vazios")

    bad_cnae = (~emp["cnae_principal"].astype(str).str.match(CNAE)).sum()
    if bad_cnae:
        report.errors.append(f"empresas.csv.cnae_principal: {bad_cnae} fora do formato 0000-0/00")
    bad_ibge = (~imo["codigo_ibge_municipio"].astype(str).str.match(IBGE)).sum()
    if bad_ibge:
        report.errors.append(
            f"enderecos.codigo_ibge_municipio: {bad_ibge} fora do formato de 7 dígitos"
        )

    no_area = int((imo["area_cadastrada_m2"] == 0).sum())
    if no_area:
        report.warnings.append(
            f"{no_area} imóveis com área 0 (tratada como ausente, não como zero)"
        )
    with_goods = imo["imovel_id"].isin(bens["imovel_id_referencia"]).sum()
    report.stats["imoveis_com_bens"] = int(with_goods)
    report.stats["cnaes_distintos"] = int(emp["cnae_principal"].nunique())
    report.stats["divisoes_cnae"] = sorted(
        emp["cnae_principal"].astype(str).str[:2].unique().tolist()
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    report = validate(args.input)
    print(json.dumps({"ok": report.ok, **report.__dict__}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report.ok else 1)


if __name__ == "__main__":
    main()
