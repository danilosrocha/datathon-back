"""Leitura da base comum → fatos por empresa + estabelecimento (input_mapping.yaml)."""

from dataclasses import dataclass, field
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from app.domain.facts import Fact, FactSource, FactStatus

MAPPING_PATH = Path(__file__).parent / "input_mapping.yaml"
RISK_TABLE = Path(__file__).resolve().parents[2] / "data" / "risco_municipio.csv"
RISK_KEYS = {
    "risco_vendaval_regiao": FactSource.API_DESASTRES,
    "risco_granizo_regiao": FactSource.API_DESASTRES,
    "risco_alagamento_regiao": FactSource.API_DESASTRES,
    "risco_roubo_regiao": FactSource.API_SEGURANCA,
}
RISK_EVIDENCE = {
    FactSource.API_DESASTRES: "Atlas Digital de Desastres 2003–2016, nível município",
    FactSource.API_SEGURANCA: "Roubos por 100 mil hab. 2018–2023, nível UF",
}
RISK_CONFIDENCE = 0.3
MONEY_BUCKETS = [
    (10_000, "ate_10k"),
    (50_000, "10k_50k"),
    (200_000, "50k_200k"),
    (1_000_000, "200k_1m"),
    (7_500_000, "1m_7_5m"),
]


@dataclass
class Case:
    empresa_id: str
    imovel_id: str
    facts: dict[str, Fact] = field(default_factory=dict)


@cache
def mapping() -> dict:
    return yaml.safe_load(MAPPING_PATH.read_text(encoding="utf-8"))


def money_range(value: float) -> str:
    return next((label for top, label in MONEY_BUCKETS if value <= top), "acima_7_5m")


def _read(base: Path, name: str) -> pd.DataFrame:
    return pd.read_csv(base / name, encoding="utf-8-sig", dtype={"codigo_ibge_municipio": str})


def load_risk_table(path: Path = RISK_TABLE) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    table = pd.read_csv(path, dtype={"municipio_ibge": str})
    return {r["municipio_ibge"]: r for r in table.to_dict("records")}


class _Builder:
    def __init__(self, as_of: datetime) -> None:
        self.as_of = as_of
        self.facts: dict[str, Fact] = {}
        cfg = mapping()
        self.by_label = cfg["confianca_rotulo"]
        self.by_status = cfg["confianca_natureza"]

    def add(
        self,
        key: str,
        value: Any,
        status: FactStatus,
        evidence: str,
        *,
        confidence: float | None = None,
        source: FactSource = FactSource.BASE_COMUM,
    ) -> None:
        self.facts[key] = Fact(
            key=key,
            value=value,
            status=status,
            source=source,
            confidence=round(confidence if confidence is not None else self.by_status[status], 2),
            evidence=evidence,
            updated_at=self.as_of,
            updated_by="lote:base_comum",
        )


def case_facts(
    empresa: dict,
    imovel: dict,
    sinais: dict,
    bens: pd.DataFrame,
    risk: dict | None,
    as_of: datetime,
) -> dict[str, Fact]:
    cfg, lim = mapping(), mapping()["limiares"]
    b = _Builder(as_of)
    OBS, DER, EST = FactStatus.OBSERVADO, FactStatus.DERIVADO, FactStatus.ESTIMADO

    # --- identificação ----------------------------------------------------------------------
    b.add(
        "cnae_principal", empresa["cnae_principal"], OBS, "empresas.cnae_principal", confidence=0.9
    )
    b.add("tipo_pessoa", "pj", DER, "empresa com CNAE na base")
    b.add("porte", empresa["porte"], OBS, "empresas.porte")
    informed = empresa["origem_faturamento"] == "INFORMADO"
    b.add(
        "faturamento_faixa",
        money_range(empresa["faturamento_mensal"] * 12),
        OBS if informed else DER,
        f"empresas.faturamento_mensal × 12 ({empresa['origem_faturamento']})",
        confidence=b.by_label[empresa["confianca_faturamento"]],
    )
    staff = int(empresa["quantidade_funcionarios_estimada"])
    band = next(label for lo, hi, label in cfg["faixas_funcionarios"] if lo <= staff <= hi)
    b.add(
        "num_empregados_faixa",
        band,
        OBS,
        f"empresas.quantidade_funcionarios_estimada = {staff}",
        confidence=0.7,
    )

    # --- local --------------------------------------------------------------------------------
    b.add(
        "municipio_ibge",
        imovel["codigo_ibge_municipio"],
        OBS,
        "enderecos.codigo_ibge_municipio",
        confidence=1.0,
    )
    b.add("uf", imovel["uf_real"], OBS, "enderecos.uf_real", confidence=1.0)
    if imovel["possui_termo_loja"] == "SIM" or imovel["possui_termo_galeria"] == "SIM":
        b.add("tipo_estabelecimento", "loja", DER, "termo LOJA/GALERIA no endereço", confidence=0.5)
    elif imovel["possui_termo_sala"] == "SIM" or imovel["possui_termo_torre"] == "SIM":
        b.add(
            "tipo_estabelecimento",
            "escritorio",
            DER,
            "termo SALA/TORRE no endereço",
            confidence=0.5,
        )
    area = float(imovel["area_cadastrada_m2"] or 0)
    if area > 0:
        b.add(
            "area_faixa",
            f"{int(area)} m²",
            OBS,
            f"enderecos.area_cadastrada_m2 ({imovel['origem_area']})",
            confidence=b.by_label[imovel["confianca_area"]],
        )

    rents = sinais["pagamento_aluguel_recorrente"] == "SIM"
    if rents:
        b.add("relacao_imovel", "inquilino", DER, "pagamento de aluguel recorrente", confidence=0.8)
        b.add("objeto_seguro", "conteudo", DER, "inquilino: protege o conteúdo", confidence=0.6)
        if sinais["valor_aluguel_recorrente"] > 0:
            b.add(
                "aluguel_mensal_faixa",
                money_range(sinais["valor_aluguel_recorrente"]),
                OBS,
                "sinais.valor_aluguel_recorrente",
                confidence=0.9,
            )
    else:
        b.add(
            "relacao_imovel",
            "proprietario",
            DER,
            "sem pagamento de aluguel recorrente",
            confidence=0.5,
        )
        b.add("objeto_seguro", "ambos", DER, "proprietário: imóvel e conteúdo", confidence=0.5)
        if area > 0:
            standard = imovel["padrao_construtivo_cadastrado"]
            m2 = cfg["custo_m2"][standard]
            # Custo por m² é premissa; sem padrão construtivo cadastrado, a premissa pesa mais.
            b.add(
                "valor_predio_faixa",
                money_range(area * m2),
                DER,
                f"área {int(area)} m² × R$ {m2}/m² ({standard})",
                confidence=0.4 if standard == "NAO_DISPONIVEL" else 0.6,
            )

    # --- impedimentos: só o que a base informa; o resto fica pendente (L-05) ---------------
    situation = imovel["situacao_imovel_cadastral"]
    b.add(
        "imovel_em_obra",
        situation == "EM_OBRA",
        OBS,
        f"enderecos.situacao_imovel_cadastral = {situation}",
    )
    wall = imovel["material_parede_externa_cadastrado"]
    if wall in ("ALVENARIA", "CONCRETO"):
        b.add(
            "parede_externa_combustivel", False, OBS, f"enderecos.material_parede_externa = {wall}"
        )

    # --- operação -------------------------------------------------------------------------
    no_public = empresa["grupo_atividade"] in cfg["sem_atendimento_presencial"]
    b.add(
        "atendimento_presencial",
        not no_public,
        DER,
        f"grupo_atividade = {empresa['grupo_atividade']}",
        confidence=0.6,
    )
    delivery_share = empresa["percentual_receita_delivery_est"]
    p_delivery = sinais["probabilidade_delivery_referencia"]
    if delivery_share >= lim["delivery_receita_min"]:
        b.add("delivery", True, OBS, f"receita de delivery {delivery_share:.0%}", confidence=0.7)
    elif p_delivery >= lim["probabilidade_sim"]:
        b.add(
            "delivery",
            True,
            EST,
            f"probabilidade_delivery_referencia = {p_delivery}",
            confidence=p_delivery,
        )
    elif delivery_share == 0 and p_delivery <= lim["probabilidade_nao"]:
        b.add(
            "delivery",
            False,
            EST,
            f"probabilidade_delivery_referencia = {p_delivery}",
            confidence=1 - p_delivery,
        )
    online = empresa["percentual_vendas_online_estimado"]
    if online >= lim["vendas_online_min"]:
        b.add("vende_online", True, OBS, f"vendas online {online:.0%}", confidence=0.7)
    elif online <= lim["vendas_online_max_nao"]:
        b.add("vende_online", False, OBS, f"vendas online {online:.0%}", confidence=0.7)

    # --- digital --------------------------------------------------------------------------
    digital = sinais["percentual_recebimentos_digitais"]
    if digital >= lim["recebimentos_digitais_min"]:
        b.add("recebe_pagamentos_online", True, OBS, f"recebimentos digitais {digital:.0%}")
    elif digital <= lim["recebimentos_digitais_max_nao"]:
        b.add("recebe_pagamentos_online", False, OBS, f"recebimentos digitais {digital:.0%}")
    exposure = sinais["indice_exposicao_digital"]
    low, high = lim["exposicao_digital_cortes"]
    level = "baixo" if exposure <= low else "medio" if exposure <= high else "alto"
    b.add("exposicao_digital_nivel", level, DER, f"indice_exposicao_digital = {exposure}")
    p_data = sinais["probabilidade_tratamento_dados"]
    if p_data >= lim["probabilidade_sim"]:
        b.add(
            "armazena_dados_clientes",
            True,
            EST,
            f"probabilidade_tratamento_dados = {p_data}",
            confidence=p_data,
        )
    elif p_data <= lim["probabilidade_nao"]:
        b.add(
            "armazena_dados_clientes",
            False,
            EST,
            f"probabilidade_tratamento_dados = {p_data}",
            confidence=1 - p_data,
        )
    dependency = empresa["dependencia_digital_pct"]
    if dependency >= lim["sistema_critico_dependencia_min"]:
        b.add(
            "sistema_critico_online",
            True,
            OBS,
            f"dependência digital {dependency}%",
            confidence=0.7,
        )
    elif dependency <= lim["sistema_critico_dependencia_max_nao"]:
        b.add(
            "sistema_critico_online",
            False,
            OBS,
            f"dependência digital {dependency}%",
            confidence=0.7,
        )

    # --- estoque e despesas -----------------------------------------------------------------
    stock = sinais["estoque_medio_estimado"]
    b.add(
        "possui_estoque",
        stock >= lim["estoque_relevante_min"],
        DER,
        f"estoque médio estimado R$ {stock:,.0f}",
    )
    if stock > 0:
        b.add("valor_estoque_faixa", money_range(stock), DER, "sinais.estoque_medio_estimado")
    b.add(
        "despesas_fixas_mensais_faixa",
        money_range(sinais["despesa_fixa_mensal_estimada"]),
        DER,
        "sinais.despesa_fixa_mensal_estimada",
    )

    # --- bens vinculados ao estabelecimento (valor ponderado pela probabilidade do vínculo) ---
    # A confiança de cada valor calculado herda a qualidade do vínculo dos bens que o compõem
    # (nivel_confianca_vinculo ALTA/MEDIA/BAIXA), ponderada pelo valor de cada bem.
    def link_quality(rows: pd.DataFrame) -> float:
        value = rows["valor_bem_ponderado_referencia"]
        quality = rows["nivel_confianca_vinculo"].map(b.by_label)
        return float((value * quality).sum() / value.sum()) if value.sum() > 0 else 0.0

    def of_types(types_: list[str]) -> pd.DataFrame:
        return bens[bens["tipo_bem"].isin(types_)]

    goods_value = float(bens["valor_bem_ponderado_referencia"].sum())
    equipment_rows = of_types(cfg["bens_equipamento"])
    equipment = float(equipment_rows["valor_bem_ponderado_referencia"].sum())
    if equipment > 0:
        b.add(
            "valor_equipamentos_faixa",
            money_range(equipment),
            DER,
            "soma ponderada de bens de equipamento",
            confidence=link_quality(equipment_rows),
        )
    if goods_value + stock > 0:
        # Estoque médio entra com a qualidade de um valor derivado (0,7).
        content_quality = (link_quality(bens) * goods_value + 0.7 * stock) / (goods_value + stock)
        b.add(
            "valor_conteudo_faixa",
            money_range(goods_value + stock),
            DER,
            "soma ponderada dos bens + estoque médio",
            confidence=content_quality,
        )

    def best_link(types_: list[str]) -> float | None:
        """Melhor vínculo (ALTA/MEDIA) entre os bens do tipo; None se só houver vínculo BAIXA."""
        rows = of_types(types_)
        rows = rows[rows["nivel_confianca_vinculo"].isin(["ALTA", "MEDIA"])]
        return None if rows.empty else max(b.by_label[v] for v in rows["nivel_confianca_vinculo"])

    if (q := best_link(cfg["bens_maquina"])) is not None:
        b.add(
            "maquinas_equipamentos",
            True,
            OBS,
            "bem de máquina/equipamento vinculado ao imóvel",
            confidence=q,
        )
    electronics_rows = of_types(cfg["bens_eletronicos"])
    electronics = float(electronics_rows["valor_bem_ponderado_referencia"].sum())
    if electronics >= lim["eletronicos_relevantes_min"]:
        b.add(
            "eletronicos_relevantes",
            True,
            DER,
            f"eletrônicos e informática R$ {electronics:,.0f}",
            confidence=link_quality(electronics_rows),
        )
    if (q := best_link(["LETREIRO"])) is not None:
        b.add(
            "letreiro_luminoso",
            True,
            OBS,
            "letreiro cadastrado e vinculado ao imóvel",
            confidence=q,
        )
    p_cold = sinais["probabilidade_refrigeracao_referencia"]
    if (q := best_link(["EQUIPAMENTO_REFRIGERACAO"])) is not None:
        b.add(
            "mercadoria_refrigerada",
            True,
            OBS,
            "equipamento de refrigeração vinculado ao imóvel",
            confidence=q,
        )
    elif p_cold >= lim["probabilidade_sim"]:
        b.add(
            "mercadoria_refrigerada",
            True,
            EST,
            f"probabilidade_refrigeracao_referencia = {p_cold}",
            confidence=p_cold,
        )
    elif p_cold <= lim["probabilidade_nao"]:
        b.add(
            "mercadoria_refrigerada",
            False,
            EST,
            f"probabilidade_refrigeracao_referencia = {p_cold}",
            confidence=1 - p_cold,
        )

    # --- risco regional: só por município (sempre estimado) ----------------------------------
    for key, source in RISK_KEYS.items():
        if risk and isinstance(risk.get(key), str):
            b.add(
                key,
                risk[key],
                EST,
                RISK_EVIDENCE[source],
                confidence=RISK_CONFIDENCE,
                source=source,
            )

    return b.facts


def load_cases(base: Path, as_of: datetime, risk_path: Path = RISK_TABLE) -> list[Case]:
    """Um caso por linha de template_resultado_times.csv (garante 100% dos casos)."""
    template = _read(base, "template_resultado_times.csv")
    empresas = _read(base, "empresas.csv").set_index("empresa_id")
    imoveis = _read(base, "enderecos_estabelecimentos.csv").set_index("imovel_id")
    sinais = _read(base, "sinais_financeiros_operacionais.csv").set_index("imovel_id")
    bens = _read(base, "bens_cadastrados.csv")
    goods = dict(tuple(bens.groupby("imovel_id_referencia")))
    empty_goods = bens.iloc[0:0]
    risk = load_risk_table(risk_path)

    cases = []
    for empresa_id, imovel_id in template[["empresa_id", "imovel_id"]].itertuples(index=False):
        imovel = imoveis.loc[imovel_id].to_dict()
        facts = case_facts(
            empresas.loc[empresa_id].to_dict(),
            imovel,
            sinais.loc[imovel_id].to_dict(),
            goods.get(imovel_id, empty_goods),
            risk.get(imovel["codigo_ibge_municipio"]),
            as_of,
        )
        cases.append(Case(empresa_id, imovel_id, facts))
    return cases
