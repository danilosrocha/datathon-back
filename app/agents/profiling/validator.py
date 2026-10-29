"""Validador da explicação do LLM (ARQUITETURA §5.3). Reprova se:
(a) cita cobertura que não está na oferta; (b) cita valor em R$ que não está na saída
estruturada; (c) promete indenização. Reprovou → texto de template."""

import re

from app.domain.decision import Offer
from app.engine.catalog import Catalog

MONEY = re.compile(r"R\$\s*([\d.]+(?:,\d+)?)\s*(mil|milh(?:ão|ões))?", re.IGNORECASE)
PROMISES = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"garant\w*\s+(?:a\s+|que\s+)?(?:indeniza|pagamento|reembolso)",
        r"indeniza\w*\s+garantid",
        r"(?:vai|v[aã]o|ir[aá]|ir[aã]o)\s+receber",
        r"receber[aá]\s+(?:a\s+)?indeniza",
        r"cobre\s+tudo",
        r"100\s*%\s*(?:protegid|cobert)",
        r"sem\s+risco\s+nenhum",
    )
]
SCALE = {"mil": 1_000, "milhão": 1_000_000, "milhões": 1_000_000}


def _amount(number: str, scale: str | None) -> int:
    value = float(number.replace(".", "").replace(",", "."))
    return round(value * SCALE.get((scale or "").lower(), 1))


def allowed_values(offer: Offer) -> set[int]:
    values = set()
    for c in offer.coverages:
        if c.insured_amount:
            values |= {c.insured_amount.min, c.insured_amount.max}
    if offer.quote_prefill:
        values |= {c.is_sugerida for c in offer.quote_prefill.coberturas if c.is_sugerida}
    return values


def validate_explanation(text: str, offer: Offer, catalog: Catalog) -> list[str]:
    problems = []
    included = {c.code for c in offer.coverages}
    lowered = text.lower()
    for code, cov in catalog.coverages.items():
        mentioned = code in text or cov.nome.lower() in lowered
        if mentioned and code not in included:
            problems.append(f"cita cobertura fora da oferta: {cov.nome}")
    allowed = allowed_values(offer)
    for number, scale in MONEY.findall(text):
        if _amount(number, scale) not in allowed:
            problems.append(f"valor não presente na oferta: R$ {number} {scale}".strip())
    problems += [f"promessa de indenização: {p.pattern}" for p in PROMISES if p.search(text)]
    return problems
