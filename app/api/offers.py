"""Ofertas: cards de cobertura e Personalizar (CONTRATOS_API §6.1).

As ofertas ficam num repositório em memória até a camada de banco (db/repositories) existir.
"""

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from app.domain.decision import CoverageCard, CustomizeRequest, Offer
from app.domain.facts import Fact
from app.engine.catalog import Catalog
from app.engine.customize import customize
from app.graph.store import GraphSnapshot

router = APIRouter(prefix="/api/v1/cases/{case_id}/offers", tags=["offers"])
PERSONALIZED_SUFFIX = "_p"


@dataclass
class CaseOffers:
    token_hash: str
    facts: dict[str, Fact]
    base: dict[str, Offer]
    custom: dict[str, Offer] = field(default_factory=dict)  # por offer_id da oferta de origem


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _not_found(code: str, message: str) -> HTTPException:
    return HTTPException(
        404, detail={"error": {"code": code, "message": message, "retryable": False}}
    )


class OfferRepository:
    def __init__(self) -> None:
        self._cases: dict[str, CaseOffers] = {}

    def save(
        self, case_id: str, case_token: str, offers: list[Offer], facts: dict[str, Fact]
    ) -> None:
        """Grava as ofertas de `decide`; descarta personalizações anteriores do caso."""
        self.save_hashed(case_id, _hash(case_token), offers, facts)

    def save_hashed(
        self, case_id: str, token_hash: str, offers: list[Offer], facts: dict[str, Fact]
    ) -> None:
        """Como `save`, para quem guarda só o hash do token (o caso nunca guarda o token)."""
        self._cases[case_id] = CaseOffers(token_hash, facts, {o.offer_id: o for o in offers})

    def get(self, case_id: str, case_token: str | None) -> CaseOffers:
        case = self._cases.get(case_id)
        if case is None or not hmac.compare_digest(case.token_hash, _hash(case_token or "")):
            raise _not_found("case_not_found", "Caso não encontrado.")
        return case


def get_repository(request: Request) -> OfferRepository:
    return request.app.state.offers


def get_catalog(request: Request) -> Catalog:
    return request.app.state.catalog


def get_graph(request: Request) -> GraphSnapshot:
    return request.app.state.graph


CaseToken = Annotated[str | None, Header(alias="X-Case-Token")]
Repo = Annotated[OfferRepository, Depends(get_repository)]
CatalogDep = Annotated[Catalog, Depends(get_catalog)]
GraphDep = Annotated[GraphSnapshot, Depends(get_graph)]


def _base(case: CaseOffers, offer_id: str) -> Offer:
    base = case.base.get(offer_id.removesuffix(PERSONALIZED_SUFFIX))
    if base is None:
        raise _not_found("offer_not_found", "Oferta não encontrada.")
    return base


@router.get("/{offer_id}", response_model=Offer)
def get_offer(case_id: str, offer_id: str, repo: Repo, x_case_token: CaseToken = None) -> Offer:
    """Oferta com `coverage_cards`. `<offer_id>_p` devolve a personalizada atual."""
    case = repo.get(case_id, x_case_token)
    base = _base(case, offer_id)
    if not offer_id.endswith(PERSONALIZED_SUFFIX):
        return base
    if base.offer_id not in case.custom:
        raise _not_found("offer_not_found", "Oferta personalizada não encontrada.")
    return case.custom[base.offer_id]


@router.get("/{offer_id}/coverage-cards", response_model=list[CoverageCard])
def get_coverage_cards(
    case_id: str, offer_id: str, repo: Repo, x_case_token: CaseToken = None
) -> list[CoverageCard]:
    return get_offer(case_id, offer_id, repo, x_case_token).coverage_cards


@router.post(
    "/{offer_id}/customize",
    response_model=Offer,
    responses={422: {"description": "`{ violations[] }`: o motor recusou a mudança"}},
)
def customize_offer(
    case_id: str,
    offer_id: str,
    body: CustomizeRequest,
    repo: Repo,
    catalog: CatalogDep,
    graph: GraphDep,
    x_case_token: CaseToken = None,
):
    """Mudanças cumulativas sobre a personalizada atual; `reset` volta à oferta padrão."""
    case = repo.get(case_id, x_case_token)
    base = _base(case, offer_id)
    current = case.custom.get(base.offer_id)
    result = customize(base, body, case.facts, catalog, graph, current=current)
    if result.offer is None:
        return JSONResponse(
            status_code=422, content={"violations": [v.model_dump() for v in result.violations]}
        )
    if body.reset:
        case.custom.pop(base.offer_id, None)
    else:
        case.custom[base.offer_id] = result.offer
    return result.offer
