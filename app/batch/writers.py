"""Decision → linhas dos dois templates oficiais e trace.jsonl (output_mapping.yaml).
Sem LLM: justificativas e perguntas vêm da trilha, por template."""

import csv
import json
from functools import cache
from pathlib import Path

import yaml

from app.batch.loader import Case
from app.domain.decision import Decision
from app.engine.catalog import Catalog
from app.engine.explain_template import PLAN_NAMES
from app.engine.recommender import SPECIFIC_RULE_ID

MAPPING_PATH = Path(__file__).parent / "output_mapping.yaml"
RESULT_TEMPLATE = "template_resultado_times.csv"
COVERAGE_TEMPLATE = "template_coberturas_times.csv"
SPECIFIC_MOTIVE = "Há coberturas específicas da atividade, disponíveis só a partir do Prático."
NO_RULE_MOTIVE = "Sem exposição que exija as coberturas padrão; o Essencial cobre o necessário."
RISK_LABELS = {
    "risco_vendaval_regiao": "vendaval",
    "risco_granizo_regiao": "granizo",
    "risco_alagamento_regiao": "alagamento",
    "risco_roubo_regiao": "roubo",
}


@cache
def mapping() -> dict:
    return yaml.safe_load(MAPPING_PATH.read_text(encoding="utf-8"))


def official_code(code: str) -> str:
    return mapping()["codigos_cobertura"].get(code, code)


def read_header(base: Path, name: str) -> list[str]:
    with (base / name).open(encoding="utf-8-sig", newline="") as f:
        return next(csv.reader(f))


def _join(items) -> str:
    return mapping()["separador_lista"].join(items)


def _location(case: Case) -> str:
    """L-09: tipo de estabelecimento sugerido + nível de risco territorial do município."""
    facts = case.facts
    kind = facts.get("tipo_estabelecimento")
    parts = [kind.value if kind else "nao_identificado"]
    risks = [f"{label} {facts[k].value}" for k, label in RISK_LABELS.items() if k in facts]
    if risks:
        parts.append("risco territorial: " + ", ".join(risks))
    return "; ".join(parts)


def _justification(decision: Decision, catalog: Catalog) -> str:
    best = decision.offers[0]
    motives = {r.id: r.motivo for r in catalog.plan_rules} | {SPECIFIC_RULE_ID: SPECIFIC_MOTIVE}
    text = [f"Plano {PLAN_NAMES[best.plan_code]}:"]
    text += [motives[r] for r in best.plan_rule_ids if r in motives] or [NO_RULE_MOTIVE]
    text += sorted({r.text for r in best.reasons if r.rule_id.startswith("REC-")})
    if decision.status == "preliminar":
        text.append("Recomendação preliminar: impedimentos sem informação na base a confirmar.")
    return " ".join(text)


def _sources(case: Case) -> str:
    cfg = mapping()
    used = sorted({f.source.value for f in case.facts.values()} & set(cfg["fontes"]))
    return _join(f"{cfg['fontes'][s]}, acesso em {cfg['data_acesso']}" for s in used)


def result_row(case: Case, decision: Decision, catalog: Catalog) -> dict[str, str]:
    eligibility = decision.eligibility
    relation = case.facts.get("relacao_imovel")
    row = {
        "empresa_id": case.empresa_id,
        "imovel_id": case.imovel_id,
        "elegivel": mapping()["elegivel"][eligibility.status],
        "motivo_inelegibilidade": _join(
            f"{b.rule_id}: {b.description}" for b in eligibility.blockers
        ),
        "tipo_localizacao_sugerido": _location(case),
        "relacao_imovel_sugerida": relation.value if relation else "",
        "plano_recomendado": "",
        "coberturas_recomendadas": "",
        "confianca_geral": "",
        "justificativa_recomendacao": "",
        "perguntas_confirmacao": "",
        "fontes_publicas_adicionais": _sources(case),
    }
    if eligibility.redirect_to:
        row["motivo_inelegibilidade"] += f" — encaminhar para {eligibility.redirect_to}"
    if not decision.offers:
        row["justificativa_recomendacao"] = "Inelegível: " + row["motivo_inelegibilidade"]
        return row
    best = decision.offers[0]
    row |= {
        "plano_recomendado": best.plan_code,
        "coberturas_recomendadas": _join(official_code(c.code) for c in best.coverages),
        "confianca_geral": f"{decision.confidence.overall:.2f}",
        "justificativa_recomendacao": _justification(decision, catalog),
        "perguntas_confirmacao": _join(decision.confirmation_questions),
    }
    return row


def coverage_rows(case: Case, decision: Decision, catalog: Catalog) -> list[dict[str, str]]:
    """Uma linha por cobertura da oferta recomendada (fixas + adicionais). Assistências não
    entram; caso inelegível não tem linhas (L-04)."""
    if not decision.offers:
        return []
    notes = mapping()["observacoes_cobertura"]
    rows = []
    for c in decision.offers[0].coverages:
        rule = catalog.estimates.rules.get(c.code)
        amount = c.insured_amount
        rows.append(
            {
                "empresa_id": case.empresa_id,
                "imovel_id": case.imovel_id,
                "cobertura": official_code(c.code),
                "faixa_valor_min": str(amount.min) if amount else "",
                "faixa_valor_max": str(amount.max) if amount else "",
                "confianca_estimativa": f"{c.confidence:.2f}" if c.confidence is not None else "",
                "dados_utilizados": _join(c.data_used),
                "regra_calculo_utilizada": f"{rule.id}: {rule.regra}" if rule else "",
                "justificativa": c.justification,
                "informacao_a_confirmar": _join(c.to_confirm),
                "observacao": " ".join(n for n in (c.note, notes.get(c.code)) if n),
            }
        )
    return rows


def write_csv(path: Path, header: list[str], columns: dict[str, str], rows: list[dict]) -> None:
    with path.open("w", encoding=mapping()["encoding"], newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for row in rows:
            writer.writerow([row[columns[col]] for col in header])


def trace_line(case: Case, decision: Decision) -> str:
    facts = {
        k: f.model_dump(
            mode="json", include={"value", "status", "source", "confidence", "evidence"}
        )
        for k, f in sorted(case.facts.items())
    }
    # Recomendada completa (com quote_prefill); alternativas resumidas para o trace caber em disco.
    dump = decision.model_dump(mode="json", exclude={"offers"})
    offers = [
        o.model_dump(mode="json", exclude={"explanation_md"})
        if i == 0
        else o.model_dump(mode="json", include={"offer_id", "kind", "plan_code", "diff_vs_best"})
        for i, o in enumerate(decision.offers)
    ]
    payload = {
        "empresa_id": case.empresa_id,
        "imovel_id": case.imovel_id,
        "facts": facts,
        "decision": dump | {"offers": offers},
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
