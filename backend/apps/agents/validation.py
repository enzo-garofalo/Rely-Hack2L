"""Validation Agent (G4): resolve SKUs contra o catálogo real, calcula o
total e formula esclarecimento quando há ambiguidade.

"É onde vive a maior parte da lógica determinística" (AGENTS_PLAN.md) —
por isso a maior parte deste módulo é Python puro chamando as tools de
tools.py, sem LLM. O único ponto onde cabe interpretação de linguagem é
genuinamente de linguagem: quando sobra mais de um candidato real do
catálogo e o cliente responde em texto livre qual deles quis dizer. É o
único lugar deste agente que chama o modelo.
"""

from __future__ import annotations

from pydantic import BaseModel

from apps.core.models import AgentRun

from . import audit, tools
from .context import OrderContext
from .llm_client import LLMOutputError, call_structured
from .schemas import (
    AgentName,
    AgentResult,
    AgentStatus,
    Ambiguity,
    AmbiguousItem,
    MemoryHint,
    OrderItemDraft,
    ResolvedItem,
    ValidatedOrder,
)

_NEGATIVE_WORDS = {"não", "nao", "n"}


class _ClarificationChoice(BaseModel):
    """Schema interno só deste módulo — não é um dos contratos congelados
    de schemas.py, porque não é saída de agente, é um passo intermediário
    de interpretação. `chosenSku` só é aceito se estiver entre os
    candidatos reais oferecidos (checado em `_confirm_candidate`)."""

    chosenSku: str | None


def run(context: OrderContext, item_ref: str | None) -> AgentResult:
    """Assinatura compatível com `orchestrator.ValidationRunner`.

    `item_ref=None` valida o pedido inteiro (primeira passada, depois do
    Intake). `item_ref` preenchido reprocessa **só** aquele item (patch,
    guardrail do Supervisor) — os demais itens resolvidos/ambíguos são
    carregados de `context` sem serem tocados de novo.
    """

    agent_run = audit.start_agent_run(context, AgentName.VALIDATION)

    if item_ref is not None:
        resolved: list[ResolvedItem] = [r for r in context.resolvedItems if r.itemRef != item_ref]
        ambiguous: list[AmbiguousItem] = [a for a in context.ambiguities if a.itemRef != item_ref]
        items_to_process = [item for item in context.items if item.id == item_ref]
    else:
        resolved = []
        ambiguous = []
        items_to_process = context.items

    for item in items_to_process:
        outcome = _resolve_item(context, item, agent_run, is_reprocess=item_ref is not None)
        if isinstance(outcome, ResolvedItem):
            resolved.append(outcome)
        else:
            ambiguous.append(outcome)

    total = None
    if not ambiguous:
        # total só existe com o pedido inteiro resolvido, e sempre via
        # calculate_total (guardrail #2 do CLAUDE.md) — nunca somado aqui.
        quantity_by_ref = {item.id: item.quantity for item in context.items}
        line_items = [(quantity_by_ref[r.itemRef], r.unitPrice) for r in resolved]
        total = tools.calculate_total(line_items, agent_run=agent_run)

    validated = ValidatedOrder(items=[*resolved, *ambiguous], total=total)
    result = AgentResult(agent=AgentName.VALIDATION, status=AgentStatus.OK, data=validated)
    next_state = "waiting_customer" if ambiguous else "ready_for_confirmation"
    audit.finish_agent_run(agent_run, next_state=next_state, result=result)
    return result


def _resolve_item(
    context: OrderContext,
    item: OrderItemDraft,
    agent_run: AgentRun,
    *,
    is_reprocess: bool,
) -> ResolvedItem | AmbiguousItem:
    hint = _find_sku_hint(context.hints, item.id)
    chosen_sku: str | None = None
    candidates: list[tools.CatalogMatch] = []

    if is_reprocess:
        # Patch: o cliente já respondeu à pergunta de esclarecimento
        # anterior. Usa os candidatos reais daquela ambiguidade + a
        # resposta livre pra decidir — não recomeça do texto original do
        # item do zero (guardrail do Supervisor).
        previous = next((a for a in context.ambiguities if a.itemRef == item.id), None)
        reply = context.latest_customer_reply(item.id)
        if previous is not None and previous.ambiguities and reply is not None:
            previous_candidates = previous.ambiguities[0].candidates
            chosen_sku = _confirm_candidate(item, previous_candidates, reply)

    if chosen_sku is None and hint is not None:
        # Guardrail: só aceita o SKU sugerido pela memória se ele ainda
        # existir no catálogo. Sem uma tool dedicada a "buscar por SKU
        # exato" (deliberadamente não criamos uma nova tool), usamos
        # check_inventory como confirmação de existência — todo ErpProduct
        # tem um ErpInventory 1:1, então None aqui significa "não existe".
        if tools.check_inventory(hint.suggests.value, agent_run=agent_run) is not None:
            chosen_sku = hint.suggests.value

    if chosen_sku is None:
        candidates = tools.search_catalog(item.productGuess, agent_run=agent_run)
        if len(candidates) == 1:
            chosen_sku = candidates[0].sku

    if chosen_sku is None:
        question = _build_clarification_question(item, candidates)
        return AmbiguousItem(
            itemRef=item.id,
            ambiguities=[Ambiguity(field="sku", question=question, candidates=[c.sku for c in candidates])],
        )

    price = tools.get_price(chosen_sku, context.customer.id, agent_run=agent_run)
    inventory = tools.check_inventory(chosen_sku, agent_run=agent_run)
    if price is None or inventory is None:
        return AmbiguousItem(
            itemRef=item.id,
            ambiguities=[
                Ambiguity(
                    field="sku",
                    question=(
                        f'Não encontrei preço ou estoque cadastrado para "{item.rawText}" '
                        f"(SKU {chosen_sku}) para este cliente — pode confirmar o produto?"
                    ),
                    candidates=[chosen_sku],
                )
            ],
        )

    # unit_label só vem do catálogo quando passamos por search_catalog
    # nesta chamada; quando o SKU veio de hint ou de reprocessamento,
    # caímos de volta pro texto informal do cliente (item.unit) — sem uma
    # tool de "buscar produto por SKU", não há como confirmar o rótulo
    # oficial do catálogo nesses dois caminhos.
    unit_label = next((c.unitLabel for c in candidates if c.sku == chosen_sku), item.unit)
    return ResolvedItem(itemRef=item.id, sku=chosen_sku, unit=unit_label, unitPrice=price, inStock=inventory.inStock)


def _find_sku_hint(hints: list[MemoryHint], item_id: str) -> MemoryHint | None:
    return next((h for h in hints if h.itemRef == item_id and h.suggests.field == "sku"), None)


def _build_clarification_question(item: OrderItemDraft, candidates: list[tools.CatalogMatch]) -> str:
    """Pergunta sempre lastreada em dado real do catálogo — nunca uma
    dúvida genérica inventada (guardrail do Validation no AGENTS_PLAN.md)."""

    if not candidates:
        return f'Não encontrei nenhum produto correspondente a "{item.rawText}". Pode confirmar o nome ou o SKU?'
    options = " ou ".join(f"{c.name} ({c.sku})" for c in candidates)
    return f'Você quis dizer {options} para "{item.rawText}"?'


def _confirm_candidate(item: OrderItemDraft, candidate_skus: list[str], reply: str) -> str | None:
    """Decide qual candidato (se algum) a resposta livre do cliente
    confirma. Com 1 candidato só, um guard textual básico (sem negativa
    explícita) já resolve — não precisa de LLM pra "sim, é isso". Com 2+,
    aí sim é interpretação de linguagem de verdade, e é o único ponto
    deste agente que chama o modelo."""

    if not candidate_skus:
        return None

    if len(candidate_skus) == 1:
        first_word = reply.strip().lower().split(" ", 1)[0].strip(".,!?")
        if first_word in _NEGATIVE_WORDS:
            return None
        return candidate_skus[0]

    messages = [
        {
            "role": "system",
            "content": (
                "O cliente respondeu a uma pergunta de esclarecimento sobre qual produto "
                "ele quis dizer. Escolha, entre os candidatos fornecidos, qual SKU a resposta "
                "confirma. Se a resposta não confirmar nenhum candidato com segurança, devolva "
                "chosenSku null — nunca escolha um SKU fora da lista de candidatos."
            ),
        },
        {
            "role": "user",
            "content": f'Item original: "{item.rawText}". Candidatos: {candidate_skus}. Resposta do cliente: "{reply}"',
        },
    ]

    try:
        choice = call_structured(agent=AgentName.VALIDATION, messages=messages, output_schema=_ClarificationChoice)
    except (LLMOutputError, RuntimeError):
        # RuntimeError também: config de LLM incompleta (ver intake.py). Sem
        # capturar aqui, o erro escaparia de `run()` inteiro e deixaria o
        # AgentRun do Validation (aberto lá em cima) sem fechar — em vez
        # disso, trata como "não deu pra confirmar" (vira ambiguidade de
        # novo, nunca escolhe um candidato às cegas).
        return None

    if choice.chosenSku in candidate_skus:
        return choice.chosenSku
    return None
