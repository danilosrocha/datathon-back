"""Cards de cobertura da oferta: cada cobertura do catálogo como incluída, disponível ou bloqueada.
Função pura; as mesmas regras de `customize` decidem o que pode ser incluído."""

from app.domain.decision import CoverageCard, InsuredAmount, Offer
from app.domain.facts import Fact
from app.engine.catalog import Catalog, Coverage
from app.engine.rules import Tri, evaluate, usable_values

GROUP_ORDER = ("fixa", "padrao_plano", "especifica_atividade", "opcional")
FIXED_LOCK = "Cobertura obrigatória em todos os planos; só a importância segurada muda."


def card_order(catalog: Catalog, code: str) -> tuple[int, str]:
    return GROUP_ORDER.index(catalog.coverages[code].grupo), code


def applicability(cov: Coverage, facts: dict[str, Fact]) -> Tri:
    """`quando` da cobertura contra fatos sabidos. Estimado não bloqueia; ausência não é "não"."""
    if cov.quando is None:
        return Tri.VERDADEIRO
    return evaluate(cov.quando, usable_values(facts, include_estimated=False)).value


def lock_reason(
    cov: Coverage, plan_code: str, facts: dict[str, Fact], catalog: Catalog
) -> str | None:
    """Motivo para a cobertura não poder entrar na oferta deste plano; None se pode."""
    plan = catalog.plans[plan_code]
    if cov.grupo == "padrao_plano" and cov.codigo not in plan.padrao:
        return "Não faz parte deste plano; escolha um plano acima (L-01)."
    if cov.grupo == "especifica_atividade" and not plan.permite_especificas:
        return "Coberturas específicas da atividade só no Prático ou no Total."
    if applicability(cov, facts) is Tri.FALSO:
        return "Não se aplica ao que foi informado sobre o negócio."
    return None


def build_cards(
    offer: Offer, facts: dict[str, Fact], catalog: Catalog, suggested: set[str] | None = None
) -> list[CoverageCard]:
    """`suggested`: códigos da oferta de origem do motor (padrão: a própria oferta)."""
    included = {c.code: c for c in offer.coverages}
    suggested = set(included) if suggested is None else suggested
    cards = []
    for code in sorted(catalog.coverages, key=lambda c: card_order(catalog, c)):
        cov = catalog.coverages[code]
        limits = (
            InsuredAmount(min=cov.is_min, max=cov.is_max)
            if cov.is_min is not None and cov.is_max is not None
            else None
        )
        card = CoverageCard(
            code=code,
            name=cov.nome,
            group=cov.grupo,
            dimension=cov.dimensao,
            status="disponivel",
            suggested=code in suggested,
            is_limits=limits,
        )
        item = included.get(code)
        if item is not None:
            card.status = "incluida"
            card.origin = item.origin
            card.insured_amount = item.insured_amount
            card.is_escolhida = item.is_escolhida
            card.justification = item.justification
            if cov.grupo == "fixa":
                card.actions = ["ajustar_is"]
                card.lock_reason = FIXED_LOCK
            else:
                card.actions = ["ajustar_is", "remover"]
            amount, chosen = item.insured_amount, item.is_escolhida
            if amount and chosen is not None and not amount.min <= chosen <= amount.max:
                card.warning = "Valor escolhido fora da faixa sugerida para o seu negócio."
        elif reason := lock_reason(cov, offer.plan_code, facts, catalog):
            card.status = "indisponivel"
            card.lock_reason = reason
        else:
            card.actions = ["adicionar"]
            if card.suggested:
                card.warning = "Sugerida para o seu negócio e retirada por você."
            elif applicability(cov, facts) is Tri.DESCONHECIDO:
                card.warning = "Confirme se isso faz parte da sua operação antes de incluir."
        cards.append(card)
    return cards
