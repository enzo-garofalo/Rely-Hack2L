"""Tools determinísticas usadas pelos agentes (task E5 do PLANO_IMPLEMENTACAO.md).

Cada função aqui é Python puro ou uma consulta direta ao banco — nenhuma
chama LLM. É a única forma como os agentes tocam dado comercial real
(catálogo, preço, estoque, memória, ERP): a frase do CLAUDE.md "o modelo
interpreta, não inventa" só é verdade porque quem busca o dado é este
módulo, nunca o texto livre de uma resposta de LLM.

Decisão de arquitetura (diverge do CLAUDE.md, que descreve acesso ao ERP
"via HTTP" com API key + Idempotency-Key): esta equipe optou por chamar
as funções puras direto — sem subir uma API HTTP própria pro ERP
simulado. As tools acessam os models via Django ORM diretamente; não há
plano de trocar isso por `requests` mais adiante.

Toda tool recebe um `agent_run` (apps.core.models.AgentRun) obrigatório e
grava um ToolCall vinculado a ele — cumpre o DoD da task E5 ("dá pra
chamar cada tool via shell do Django e ver o ToolCall gravado") e a
trilha de auditoria (RF38). `agent_run` é obrigatório, não opcional, de
propósito: uma tool chamada sem AgentRun associado seria uma ação sem
auditoria, o que o projeto não permite.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import Iterable

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.models import AgentRun, MemoryEntry, MemoryProposal, ToolCall
from apps.erp_simulator.models import ErpIdempotencyKey, ErpInventory, ErpOrder, ErpPrice, ErpProduct

from .sanitize import sanitize


def _log_tool_call(
    agent_run: AgentRun,
    tool_name: str,
    input_data: dict,
    output_data: dict,
    *,
    success: bool = True,
    error_message: str = "",
) -> None:
    """Grava a chamada na auditoria. Único ponto do arquivo que cria um
    ToolCall — todas as tools passam por aqui, sempre no fim (com o
    resultado já em mãos), nunca antes. `sanitize` (E8, RF38) roda aqui
    para que toda tool, presente e futura, saia sanitizada sem precisar
    lembrar de chamar nada por conta própria."""

    ToolCall.objects.create(
        agent_run=agent_run,
        tool_name=tool_name,
        input_data=sanitize(input_data),
        output_data=sanitize(output_data),
        success=success,
        error_message=sanitize(error_message),
    )


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------


def _texts_overlap(a: str, b: str) -> bool:
    """True se `a` está contido em `b` ou `b` está contido em `a`
    (ambos já em minúsculas). Usado por `search_catalog` pra casar tanto
    "coca" -> "Refrigerante Cola 2L" (alias curto, nome longo) quanto
    "coca 2L" -> "coca" (descrição do cliente mais longa que o alias)."""

    return bool(a) and bool(b) and (a in b or b in a)


@dataclass
class CatalogMatch:
    """Um produto real do catálogo. É só isso que o Validation Agent pode
    usar como SKU — nunca um valor "lembrado" pelo modelo (guardrail:
    "aceita somente SKUs retornados pelo catálogo")."""

    sku: str
    name: str
    unitLabel: str


def search_catalog(query: str, *, agent_run: AgentRun) -> list[CatalogMatch]:
    """Resolve um nome informal (ex.: "breja", "coca 2L") em produtos
    reais, casando contra o nome do produto E os apelidos cadastrados em
    ErpAlias — é assim que "breja" vira CERV-PILSEN-350. Só considera
    produtos `active=True`. Lista vazia significa "nenhum candidato
    real": o Validation deve tratar como ambiguidade sem match, nunca
    inventar um SKU parecido.

    A comparação é nos dois sentidos (substring em qualquer direção),
    não só "query contida no nome/alias": o Intake normalmente descreve
    um item como "coca 2L" ou "2 caixas de coca", que não é substring
    literal nem do alias cadastrado ("coca") nem do nome do produto
    ("Refrigerante Cola 2L") — só o contrário é verdade. Só checar um
    sentido (como esta função fazia antes) deixava a maioria dos itens
    reais caindo em ambiguidade falsa mesmo com um match óbvio no
    catálogo. Feito em Python (não em SQL) porque "X contém Y" com Y
    variável por linha não dá pra expressar num único `Q()`/`icontains`;
    o catálogo de uma demo é pequeno o bastante pra isso não pesar.
    """

    normalized = query.strip().lower()
    matches: list[CatalogMatch] = []
    if normalized:
        for product in ErpProduct.objects.filter(active=True).prefetch_related("aliases"):
            candidates_text = [product.name, *[a.alias_text for a in product.aliases.all()]]
            if any(_texts_overlap(normalized, text.lower()) for text in candidates_text):
                matches.append(CatalogMatch(sku=product.sku, name=product.name, unitLabel=product.unit_label))

    _log_tool_call(
        agent_run,
        "search_catalog",
        {"query": query},
        {"matches": [asdict(m) for m in matches]},
    )
    return matches


def get_price(sku: str, customer_id: int, *, agent_run: AgentRun) -> float | None:
    """Preço é sempre por cliente (RF14, ver ErpPrice) — não existe
    "preço de tabela" genérico neste modelo. `None` significa que não há
    preço cadastrado para esse par produto/cliente: o Validation não deve
    inventar um valor, deve tratar o item como pendente."""

    unit_price = (
        ErpPrice.objects.filter(product__sku=sku, customer_id=customer_id)
        .values_list("unit_price", flat=True)
        .first()
    )
    result = float(unit_price) if unit_price is not None else None

    _log_tool_call(
        agent_run,
        "get_price",
        {"sku": sku, "customerId": customer_id},
        {"unitPrice": result},
    )
    return result


@dataclass
class InventoryStatus:
    inStock: bool
    quantityAvailable: int


def check_inventory(sku: str, *, agent_run: AgentRun) -> InventoryStatus | None:
    """`None` quando o SKU nem tem registro de estoque no ERP (não
    deveria acontecer se o SKU veio de `search_catalog`, mas esta tool
    não assume isso — verifica de novo) OU quando o produto foi
    desativado no catálogo. Este segundo caso importa porque esta tool
    também serve como "SKU ainda existe?" para o caminho de hint de
    memória em validation.py (que não passa por `search_catalog`, logo
    nunca vê o filtro `active=True` de lá) — sem checar `active` aqui
    também, um alias antigo confirmado poderia reviver um produto já
    descontinuado, furando o guardrail "SKU vem sempre do catálogo real"
    (CLAUDE.md #1). Sem registro ou produto inativo, trata como
    indisponível ao invés de "provavelmente tem"."""

    try:
        inventory = ErpInventory.objects.get(product__sku=sku, product__active=True)
    except ErpInventory.DoesNotExist:
        status = None
    else:
        status = InventoryStatus(
            inStock=inventory.quantity_available > 0,
            quantityAvailable=inventory.quantity_available,
        )

    _log_tool_call(
        agent_run,
        "check_inventory",
        {"sku": sku},
        {"result": asdict(status) if status is not None else None},
    )
    return status


def calculate_total(line_items: Iterable[tuple[float, float]], *, agent_run: AgentRun) -> float:
    """Função pura: soma quantidade × preço unitário. Nunca é o modelo
    "calculando" em texto livre (guardrail #2 do CLAUDE.md) — por isso
    nem toca o banco, só recebe pares (quantity, unitPrice) já resolvidos
    por quem chamou (o Validation Agent, cruzando a quantidade do
    OrderItemDraft com o unitPrice do ResolvedItem pelo itemRef)."""

    items = list(line_items)
    total = sum(quantity * unit_price for quantity, unit_price in items)

    _log_tool_call(
        agent_run,
        "calculate_total",
        {"lineItems": [{"quantity": q, "unitPrice": p} for q, p in items]},
        {"total": total},
    )
    return total


# ---------------------------------------------------------------------------
# Memória operacional
# ---------------------------------------------------------------------------


@dataclass
class MemoryAliasRecord:
    productHint: str
    sku: str


@dataclass
class MemoryPreferenceRecord:
    key: str
    value: str


@dataclass
class RecentErpOrderRecord:
    externalOrderNumber: str
    items: list[dict]
    createdAt: datetime


@dataclass
class CustomerMemorySnapshot:
    """Dado histórico cru sobre o cliente. Interpretar isso em hints com
    confiança/evidência (schemas.MemoryHint) é trabalho do Memory Agent
    (LLM) — esta tool só busca no banco, nunca decide o que sugerir."""

    aliases: list[MemoryAliasRecord]
    preferences: list[MemoryPreferenceRecord]
    recentOrders: list[RecentErpOrderRecord]


def get_customer_memory(
    customer_id: int, *, agent_run: AgentRun, recent_orders_limit: int = 5
) -> CustomerMemorySnapshot:
    """Busca aliases confirmados, preferências e os últimos pedidos reais
    do cliente no ERP. Não resolve nada sozinha — devolve o material bruto
    que o Memory Agent usa pra montar hints com evidência."""

    aliases = [
        MemoryAliasRecord(productHint=entry.product_hint, sku=entry.sku)
        for entry in MemoryEntry.objects.filter(customer_id=customer_id, kind=MemoryEntry.Kind.PRODUCT_ALIAS)
    ]
    preferences = [
        MemoryPreferenceRecord(key=entry.preference_key, value=entry.preference_value)
        for entry in MemoryEntry.objects.filter(customer_id=customer_id, kind=MemoryEntry.Kind.PREFERENCE)
    ]
    recent_orders = [
        RecentErpOrderRecord(externalOrderNumber=order.external_order_number, items=order.items, createdAt=order.created_at)
        for order in ErpOrder.objects.filter(customer_id=customer_id).order_by("-created_at")[:recent_orders_limit]
    ]
    snapshot = CustomerMemorySnapshot(aliases=aliases, preferences=preferences, recentOrders=recent_orders)

    _log_tool_call(
        agent_run,
        "get_customer_memory",
        {"customerId": customer_id},
        {
            "aliases": [asdict(a) for a in aliases],
            "preferences": [asdict(p) for p in preferences],
            "recentOrders": [
                {"externalOrderNumber": r.externalOrderNumber, "items": r.items, "createdAt": r.createdAt.isoformat()}
                for r in recent_orders
            ],
        },
    )
    return snapshot


def create_memory_proposal(
    customer_id: int,
    alias: str,
    sku: str,
    evidence: str,
    *,
    agent_run: AgentRun,
    source_order_version_id: int | None = None,
) -> MemoryProposal:
    """Sempre nasce `pending_review` — nunca aprovado por aqui (guardrail
    #5 do CLAUDE.md: "memória não substitui o ERP... aprendizado nunca é
    automático"). Quem aprova é um humano, em outro fluxo de revisão,
    fora do escopo desta tool."""

    proposal = MemoryProposal.objects.create(
        customer_id=customer_id,
        source_order_version_id=source_order_version_id,
        alias=alias,
        sku=sku,
        status=MemoryProposal.Status.PENDING_REVIEW,
        evidence=evidence,
    )

    _log_tool_call(
        agent_run,
        "create_memory_proposal",
        {"customerId": customer_id, "alias": alias, "sku": sku, "evidence": evidence},
        {"proposalId": proposal.id, "status": proposal.status},
    )
    return proposal


# ---------------------------------------------------------------------------
# ERP — escrita
# ---------------------------------------------------------------------------


def _generate_external_order_number() -> str:
    """Sufixo aleatório em vez de sequencial: evita a corrida de duas
    criações concorrentes calculando o mesmo "próximo número" a partir de
    um COUNT — o número em si não precisa ser bonito, só único."""

    return f"ERP-{timezone.now().year}-{uuid.uuid4().hex[:6].upper()}"


def create_erp_order(
    customer_id: int,
    items: list[dict],
    total: float,
    idempotency_key: str,
    *,
    agent_run: AgentRun,
) -> ErpOrder:
    """Cria o pedido no ERP simulado (system of record), com idempotência
    (guardrail #4 do CLAUDE.md). `items` segue o formato já usado pelo
    seed: `[{"sku": ..., "qty": ...}, ...]`.

    Se `idempotency_key` já foi usada — inclusive por uma chamada quase
    simultânea (ex.: timeout seguido de retry) — devolve o pedido
    existente em vez de criar outro. Nunca duplica.
    """

    existing = ErpIdempotencyKey.objects.select_related("erp_order").filter(key=idempotency_key).first()
    if existing is not None:
        _log_tool_call(
            agent_run,
            "create_erp_order",
            {"customerId": customer_id, "items": items, "total": total, "idempotencyKey": idempotency_key},
            {"externalOrderId": existing.erp_order.external_order_number, "replay": True},
        )
        return existing.erp_order

    try:
        with transaction.atomic():
            order = ErpOrder.objects.create(
                external_order_number=_generate_external_order_number(),
                customer_id=customer_id,
                items=items,
                total=Decimal(str(total)),
            )
            ErpIdempotencyKey.objects.create(
                key=idempotency_key,
                erp_order=order,
                request_payload={"customerId": customer_id, "items": items, "total": total},
            )
    except IntegrityError:
        # Corrida: outra chamada com a mesma idempotency_key venceu entre
        # o select acima e este create. Não duplica — devolve o pedido
        # que já existe de verdade, igual ao caminho feliz do replay.
        existing = ErpIdempotencyKey.objects.select_related("erp_order").get(key=idempotency_key)
        _log_tool_call(
            agent_run,
            "create_erp_order",
            {"customerId": customer_id, "items": items, "total": total, "idempotencyKey": idempotency_key},
            {"externalOrderId": existing.erp_order.external_order_number, "replay": True},
        )
        return existing.erp_order

    _log_tool_call(
        agent_run,
        "create_erp_order",
        {"customerId": customer_id, "items": items, "total": total, "idempotencyKey": idempotency_key},
        {"externalOrderId": order.external_order_number, "replay": False},
    )
    return order
