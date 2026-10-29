"""metricas.json (CONTRATOS_API §10, Guia §8)."""

from collections import Counter, defaultdict
from math import comb

from app.batch.loader import Case
from app.batch.writers import mapping
from app.domain.decision import Decision
from app.domain.facts import Fact
from app.engine.catalog import Catalog
from app.engine.decide import decide
from app.graph.store import GraphSnapshot

LOW_CONFIDENCE = 0.5
MONEY_ORDER = ["ate_10k", "10k_50k", "50k_200k", "200k_1m", "1m_7_5m", "acima_7_5m"]
BASIC = "INCENDIO_RAIO_EXPLOSAO_FUMACA"
IRRELEVANT_KEY = "porte"  # presente na base e em nenhuma regra: perturbá-lo não pode mudar nada


def _plan(decision: Decision) -> str | None:
    return decision.offers[0].plan_code if decision.offers else None


def _with(facts: dict[str, Fact], key: str, value) -> dict[str, Fact]:
    return {**facts, key: facts[key].model_copy(update={"value": value})}


def stability(cases: list[Case], decisions: list[Decision], catalog, graph) -> float:
    same = 0
    for case, decision in zip(cases, decisions, strict=True):
        current = case.facts[IRRELEVANT_KEY].value
        flipped = "PEQUENA" if current != "PEQUENA" else "MICRO"
        same += _plan(decide(_with(case.facts, IRRELEVANT_KEY, flipped), catalog, graph)) == _plan(
            decision
        )
    return same / len(cases)


def similar_consistency(cases: list[Case], decisions: list[Decision]) -> float:
    """% de pares com mesma divisão CNAE e mesmas faixas (faturamento, conteúdo) e mesmo plano."""
    groups: dict[tuple, Counter] = defaultdict(Counter)
    for case, decision in zip(cases, decisions, strict=True):
        f = case.facts
        key = tuple(
            f[k].value if k in f else None
            for k in ("faturamento_faixa", "valor_conteudo_faixa", "relacao_imovel")
        ) + (f["cnae_principal"].value[:2],)
        groups[key][_plan(decision)] += 1
    pairs = sum(comb(sum(c.values()), 2) for c in groups.values())
    same = sum(comb(n, 2) for c in groups.values() for n in c.values())
    return same / pairs if pairs else 1.0


def range_sensitivity(cases: list[Case], decisions: list[Decision], catalog, graph) -> float:
    """Variação relativa média do ponto médio da básica quando o conteúdo sobe uma faixa."""
    changes = []
    for case, decision in zip(cases, decisions, strict=True):
        fact = case.facts.get("valor_conteudo_faixa")
        if not decision.offers or fact is None or fact.value == MONEY_ORDER[-1]:
            continue
        bumped = MONEY_ORDER[MONEY_ORDER.index(fact.value) + 1]
        before = next(c for c in decision.offers[0].coverages if c.code == BASIC).insured_amount
        after_decision = decide(_with(case.facts, "valor_conteudo_faixa", bumped), catalog, graph)
        if not after_decision.offers:
            continue
        after = next(
            c for c in after_decision.offers[0].coverages if c.code == BASIC
        ).insured_amount
        mid_before, mid_after = (before.min + before.max) / 2, (after.min + after.max) / 2
        changes.append((mid_after - mid_before) / mid_before)
    return sum(changes) / len(changes) if changes else 0.0


def compute(
    cases: list[Case],
    decisions: list[Decision | None],
    coverage_rows: list[dict],
    result_rows: list[dict],
    catalog: Catalog,
    graph: GraphSnapshot,
    elapsed_s: float,
    output_hash: str,
) -> dict:
    total = len(cases)
    ok = [(c, d) for c, d in zip(cases, decisions, strict=True) if d is not None]
    ok_cases, ok_decisions = [c for c, _ in ok], [d for _, d in ok]
    eligible = [d for d in ok_decisions if d.offers]
    fixas = set(catalog.plans["ESSENCIAL"].fixas)

    rows_by_case: dict[tuple, list[dict]] = defaultdict(list)
    for r in coverage_rows:
        rows_by_case[(r["empresa_id"], r["imovel_id"])].append(r)
    reverse = {v: k for k, v in mapping()["codigos_cobertura"].items()}

    complete_fixed, inconsistent = 0, 0
    for case, decision in ok:
        if not decision.offers:
            continue
        codes = {
            reverse.get(r["cobertura"], r["cobertura"])
            for r in rows_by_case[(case.empresa_id, case.imovel_id)]
        }
        complete_fixed += fixas <= codes
        plan = catalog.plans[decision.offers[0].plan_code]
        for code in codes:
            group = catalog.coverages[code].grupo
            if (group == "padrao_plano" and code not in plan.padrao) or (
                group == "especifica_atividade" and not plan.permite_especificas
            ):
                inconsistent += 1

    violations = sum(
        bool(d.eligibility.blockers) == bool(d.offers) for d in ok_decisions
    )  # bloqueio com oferta, ou oferta sem bloqueio negada
    return {
        "casos_total": total,
        "pct_processados": len(ok) / total if total else 0.0,
        "taxa_falhas": (total - len(ok)) / total if total else 0.0,
        "tempo_execucao_s": round(elapsed_s, 2),
        "pct_com_justificativa": sum(bool(r["justificativa_recomendacao"]) for r in result_rows)
        / total,
        "violacoes_elegibilidade": violations,
        "pct_coberturas_fixas_completas": complete_fixed / len(eligible) if eligible else 1.0,
        "inconsistencias_plano_coberturas": inconsistent,
        "pct_coberturas_sem_faixa": (
            sum(not r["faixa_valor_min"] for r in coverage_rows) / len(coverage_rows)
            if coverage_rows
            else 0.0
        ),
        "media_perguntas_confirmacao": (
            sum(len(d.confirmation_questions) for d in eligible) / len(eligible)
            if eligible
            else 0.0
        ),
        "pct_confianca_baixa": (
            sum(d.confidence.overall < LOW_CONFIDENCE for d in eligible) / len(eligible)
            if eligible
            else 0.0
        ),
        "estabilidade": stability(ok_cases, ok_decisions, catalog, graph),
        "consistencia_casos_semelhantes": similar_consistency(ok_cases, ok_decisions),
        "sensibilidade_faixas": round(range_sensitivity(ok_cases, ok_decisions, catalog, graph), 4),
        "hash_reprodutibilidade": output_hash,
        "distribuicao_elegibilidade": dict(Counter(d.eligibility.status for d in ok_decisions)),
        "distribuicao_planos": dict(Counter(_plan(d) for d in eligible)),
        "versoes": ok_decisions[0].versions.model_dump() if ok_decisions else {},
    }
