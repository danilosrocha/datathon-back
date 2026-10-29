"""Faixas de importância segurada pelas regras EST-* (catalog/estimativas.yaml).

Entradas por prioridade: confirmado > observado > derivado > estimado; sem entrada, a tabela da
equipe (`padrao`, natureza estimado).

Confiança = média dos valores das *vagas* de entrada da regra (CONTRATOS_API §9.5: média
ponderada do fator × cobertura das entradas necessárias). Uma vaga é uma entrada necessária ao
caso: alternativas ("prédio **ou** conteúdo") ocupam uma vaga só, e entradas que não se aplicam
(o prédio de quem só protege o conteúdo) não contam. Vaga vazia vale 0; vaga preenchida pela
tabela da equipe vale o fator de `estimado`; vaga preenchida por um dado vale
min(fator da natureza, confiança do dado) — a natureza é o teto, a qualidade pode baixar.
"""

from dataclasses import dataclass
from typing import Any

from app.domain.decision import Hypothesis, InsuredAmount
from app.domain.fact_keys import get_fact_key
from app.domain.facts import Fact
from app.engine.catalog import Catalog, EstimateRule
from app.engine.rules import usable_values

BASIC_PARTS = {"ambos": ["predio", "conteudo"], "predio": ["predio"], "conteudo": ["conteudo"]}


@dataclass(frozen=True)
class Input:
    value: Any
    status: str
    source: str
    confidence: float = 1.0  # qualidade do próprio dado (rótulo da base, vínculo, p da hipótese)


def input_factor(item: Input, factors: dict[str, float]) -> float:
    """Valor de uma entrada: a natureza é o teto, a qualidade do dado pode baixar.
    Ex.: observado (teto 0,8) com rótulo MEDIA na base (0,6) → 0,6."""
    return min(factors[item.status], item.confidence)


@dataclass(frozen=True)
class Slot:
    """Vaga de entrada: chave a confirmar, fator de natureza (0 = vazia) e se pede confirmação."""

    key: str
    factor: float
    confirm: bool


@dataclass(frozen=True)
class Estimate:
    amount: InsuredAmount
    confidence: float
    data_used: list[str]
    calc_rule: str
    to_confirm: list[str]


def build_inputs(
    facts: dict[str, Fact], hyps: list[Hypothesis], *, include_estimated: bool
) -> dict[str, Input]:
    usable = usable_values(facts, include_estimated=include_estimated)
    inputs = {
        k: Input(v, facts[k].status.value, facts[k].source.value, facts[k].confidence)
        for k, v in usable.items()
    }
    for h in hyps:
        inputs.setdefault(h.fact_key, Input(h.value, "estimado", "grafo", h.p))
    return inputs


def _basic(rule: EstimateRule, inputs: dict[str, Input], money, factors, strict: bool):
    """Soma das faixas de prédio e/ou conteúdo. strict: sem tabela da equipe (None se faltar).
    Vagas: o objeto do seguro e cada parte que será protegida (só as que se aplicam)."""
    used, defaulted = [], False
    if "objeto_seguro" in inputs:
        item = inputs["objeto_seguro"]
        parts = BASIC_PARTS[item.value]
        slots = [Slot("objeto_seguro", input_factor(item, factors), item.status == "estimado")]
    elif "relacao_imovel" in inputs:
        # Premissa: inquilino protege só o conteúdo; proprietário, prédio e conteúdo.
        item = inputs["relacao_imovel"]
        parts = ["conteudo"] if item.value == "inquilino" else ["predio", "conteudo"]
        used.append("relacao_imovel")
        slots = [Slot("objeto_seguro", input_factor(item, factors), True)]  # inferido: confirmar
    elif strict:
        return None
    else:
        parts = ["predio", "conteudo"]
        slots = [Slot("objeto_seguro", 0.0, True)]

    lo = hi = 0
    for part in parts:
        key = f"valor_{part}_faixa"
        if key in inputs:
            rng = money[inputs[key].value]
            item = inputs[key]
            slots.append(Slot(key, input_factor(item, factors), item.status == "estimado"))
        elif strict:
            return None
        else:
            rng = money[rule.padrao[key]]
            defaulted = True
            slots.append(Slot(key, factors["estimado"], True))
        lo, hi = lo + rng[0], hi + rng[1]
    return lo, hi, used, defaulted, slots


def _slot(key: str, inputs: dict[str, Input], factors) -> Slot:
    item = inputs.get(key)
    if item is None:
        return Slot(key, 0.0, True)
    return Slot(key, input_factor(item, factors), item.status == "estimado")


def _compute(rule: EstimateRule, inputs: dict[str, Input], money, factors):
    """Devolve (min, max, entradas extras usadas, usou tabela da equipe?, vagas)."""
    table = factors["estimado"]
    if rule.tipo == "basica":
        return _basic(rule, inputs, money, factors, strict=False)

    if rule.tipo == "proporcional":
        # As bases são alternativas: uma vaga só, a da primeira disponível.
        alternatives = {b.fato for b in rule.base}
        others = [_slot(k, inputs, factors) for k in rule.entradas if k not in alternatives]
        m_lo, m_hi = rule.multiplicador
        for base in rule.base:
            if base.fato in inputs:
                rng = money[inputs[base.fato].value]
                slots = [_slot(base.fato, inputs, factors), *others]
                return rng[0] * base.fator * m_lo, rng[1] * base.fator * m_hi, [], False, slots
        lo, hi = rule.padrao
        return lo, hi, [], True, [Slot(rule.base[0].fato, table, True), *others]

    if rule.tipo == "tabela":
        others = [_slot(k, inputs, factors) for k in rule.entradas if k != rule.fato]
        item = inputs.get(rule.fato)
        if item is not None and item.value in rule.linhas:
            lo, hi = rule.linhas[item.value]
            return lo, hi, [], False, [_slot(rule.fato, inputs, factors), *others]
        lo, hi = rule.padrao
        return lo, hi, [], True, [Slot(rule.fato, table, True), *others]

    if rule.tipo == "fontes":
        # Fontes alternativas em ordem: a primeira disponível ocupa a vaga única da regra.
        for src in rule.fontes:
            if "fato" in src:
                item = inputs.get(src["fato"])
                if item is not None and item.value in src["linhas"]:
                    lo, hi = src["linhas"][item.value]
                    return lo, hi, [], False, [_slot(src["fato"], inputs, factors)]
            else:
                present = [k for k in src["fatos"] if k in inputs]
                if present:
                    lo, hi = src["linhas"][sum(inputs[k].value is True for k in present)]
                    return lo, hi, [], False, [_slot(k, inputs, factors) for k in src["fatos"]]
        lo, hi = rule.padrao
        first = rule.fontes[0]
        return lo, hi, [], True, [Slot(first.get("fato") or first["fatos"][0], table, True)]

    # contagem: cada sinal é uma vaga; sem nenhum, a tabela da equipe preenche todas (estimado).
    present = [k for k in rule.fatos if k in inputs]
    if present:
        lo, hi = rule.linhas[sum(inputs[k].value is True for k in present)]
        return lo, hi, [], False, [_slot(k, inputs, factors) for k in rule.fatos]
    lo, hi = rule.padrao
    return lo, hi, [], True, [Slot(k, table, True) for k in rule.fatos]


def estimate(code: str, inputs: dict[str, Input], catalog: Catalog) -> Estimate | None:
    est = catalog.estimates
    rule = est.rules.get(code)
    if rule is None:
        return None
    lo, hi, extra_used, defaulted, slots = _compute(
        rule, inputs, est.money_ranges, est.status_factors
    )

    # Inteiros em reais: min arredondado para baixo, max para cima, dentro dos limites da cobertura.
    step = est.rounding
    cov = catalog.coverages[code]
    lo, hi = max(int(lo) // step * step, step), -(-int(hi) // step) * step
    if cov.is_min is not None:
        lo, hi = max(lo, cov.is_min), max(hi, cov.is_min)
    if cov.is_max is not None:
        lo, hi = min(lo, cov.is_max), min(hi, cov.is_max)

    confidence = round(sum(s.factor for s in slots) / len(slots), 2)

    present = {s.key for s in slots if s.key in inputs}
    used = sorted(present | set(extra_used))
    data_used = [f"{k} ({inputs[k].status}, {inputs[k].source})" for k in used]
    if defaulted:
        data_used.append(f"tabela da equipe {rule.id} (estimado)")
    pending = {s.key for s in slots if s.confirm}
    to_confirm = [f"Confirmar: {get_fact_key(k).label.lower()}?" for k in sorted(pending)]

    return Estimate(
        amount=InsuredAmount(min=lo, max=hi),
        confidence=confidence,
        data_used=data_used,
        calc_rule=rule.id,
        to_confirm=to_confirm,
    )


def basic_minimum(inputs: dict[str, Input], catalog: Catalog) -> int | None:
    """IS básica mínima (soma dos pisos das faixas, sem teto) para a ELG-008. Só com entradas
    sabidas e pelo piso: o caso só é redirecionado quando nem o mínimo cabe no limite."""
    est = catalog.estimates
    rule = next(r for r in est.rules.values() if r.tipo == "basica")
    result = _basic(rule, inputs, est.money_ranges, est.status_factors, strict=True)
    return None if result is None else result[0]
