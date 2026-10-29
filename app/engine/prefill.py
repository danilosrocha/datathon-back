"""quote_prefill: a oferta nos campos da cotação oficial (ARQUITETURA §3.1, L-10, L-15)."""

from app.domain.decision import Address, InsuredAmount, Offer, PrefillCoverage, QuotePrefill
from app.engine.catalog import Catalog, Coverage
from app.engine.estimates import Input

IS_STEP = 5000
# CEP e coordenadas da base comum são fictícios: só entram quando vêm do usuário (web).
FICTITIOUS_SOURCES = {"base_comum"}


def suggested_is(amount: InsuredAmount | None, cov: Coverage) -> int | None:
    """Ponto médio da faixa, arredondado para baixo ao múltiplo de R$ 5 mil, dentro de
    is_min/is_max (L-15). Só para o formulário; os templates seguem com mínimo e máximo."""
    if amount is None:
        return None
    value = max((amount.min + amount.max) // 2 // IS_STEP * IS_STEP, IS_STEP)
    if cov.is_min is not None:
        value = max(value, cov.is_min)
    if cov.is_max is not None:
        value = min(value, cov.is_max)
    return value


def _insured_object(inputs: dict[str, Input]) -> str:
    """Mesma premissa da EST-BASICA-01: sem objeto informado, inquilino → conteúdo; senão ambos."""
    if "objeto_seguro" in inputs:
        return inputs["objeto_seguro"].value
    relacao = inputs.get("relacao_imovel")
    return "conteudo" if relacao and relacao.value == "inquilino" else "ambos"


def quote_prefill(
    offer: Offer,
    inputs: dict[str, Input],
    catalog: Catalog,
    *,
    vigencia_anos: int | None = None,
    chosen_is: dict[str, int] | None = None,
) -> QuotePrefill:
    def value(key: str):
        item = inputs.get(key)
        return item.value if item else None

    cep = inputs.get("cep")
    activity = catalog.activities.get(value("cnae_principal"))
    chosen_is = chosen_is or {}
    selected = (offer.premium_benefit or {}).get("selected")

    return QuotePrefill(
        tipo_pessoa=value("tipo_pessoa"),
        atividade=activity.atividade if activity else None,
        subatividade=activity.subatividade if activity else None,
        objeto_seguro=_insured_object(inputs),
        em_shopping=value("em_shopping"),
        endereco=Address(
            cep=cep.value if cep and cep.source not in FICTITIOUS_SOURCES else None,
            municipio_ibge=value("municipio_ibge"),
            uf=value("uf"),
        ),
        vigencia_anos=vigencia_anos or value("vigencia_anos") or catalog.term.padrao,
        plano=offer.plan_code,
        coberturas=[
            PrefillCoverage(
                code=c.code,
                ativa=True,
                is_sugerida=chosen_is.get(c.code)
                or suggested_is(c.insured_amount, catalog.coverages[c.code]),
            )
            for c in offer.coverages
        ],
        beneficio_premium=selected,
    )
