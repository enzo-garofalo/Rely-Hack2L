"""Operational Memory Agent (G3): consultor com evidência, nunca fonte
da verdade. Duas operações separadas (AGENTS_PLAN.md):

- `run` (recall): lida durante o intake, opcional — se não há histórico
  útil, devolve vazio e o fluxo segue sem travar.
- `propose`: roda só depois que o cliente confirma um esclarecimento;
  grava um alias observado como MemoryProposal, sempre `pending_review`.
  Mecânico (só persiste o que já foi confirmado na conversa), não usa LLM.

Guardrail central (guardrail #5 do CLAUDE.md): memória sugere, nunca
afirma. Aprendizado nunca é automático.
"""

from __future__ import annotations

import logging
import re
import unicodedata

from . import audit, tools
from .context import OrderContext
from .schemas import (
    AgentName,
    AgentResult,
    AgentStatus,
    MemoryContext,
    MemoryHint,
    MemoryHintSuggestion,
    MemoryPreference,
    MemoryProposal,
)

logger = logging.getLogger(__name__)

def _normalize(value: str) -> str:
    """Normaliza apenas para comparar aliases aprovados com a fala atual."""

    without_accents = "".join(
        char
        for char in unicodedata.normalize("NFKD", value.lower())
        if not unicodedata.combining(char)
    )
    return " ".join(re.findall(r"[a-z0-9]+", without_accents))


def _contains_phrase(text: str, phrase: str) -> bool:
    return bool(phrase) and f" {phrase} " in f" {text} "


def _recall_from_approved_memory(
    context: OrderContext,
    snapshot: tools.CustomerMemorySnapshot,
) -> MemoryContext:
    """Transforma memória já aprovada em sugestões sem inferência remota.

    Um alias só gera hint quando aparece literalmente (após normalização)
    no item atual. Se aliases compatíveis apontarem para SKUs diferentes,
    não escolhemos nenhum: o Validation fará o esclarecimento normal.
    """

    hints: list[MemoryHint] = []
    for item in context.items:
        current_text = _normalize(f"{item.rawText} {item.productGuess}")
        matching_aliases = [
            alias
            for alias in snapshot.aliases
            if alias.sku and _contains_phrase(current_text, _normalize(alias.productHint))
        ]
        matching_skus = {alias.sku for alias in matching_aliases}
        if len(matching_skus) != 1:
            continue

        strongest_alias = max(matching_aliases, key=lambda alias: len(_normalize(alias.productHint)))
        hints.append(
            MemoryHint(
                itemRef=item.id,
                type="alias_resolution",
                suggests=MemoryHintSuggestion(field="sku", value=strongest_alias.sku),
                confidence=0.98,
                evidence=(
                    f'Alias aprovado no histórico: "{strongest_alias.productHint}" '
                    f"→ {strongest_alias.sku}."
                ),
            )
        )

    preferences = [
        MemoryPreference(
            type=preference.key,
            value=preference.value,
            evidence=f'Preferência aprovada no histórico: "{preference.key}" = "{preference.value}".',
        )
        for preference in snapshot.preferences
    ]
    return MemoryContext(hints=hints, preferences=preferences)


def run(context: OrderContext) -> AgentResult:
    """Assinatura compatível com `orchestrator.AgentRunner`. Cria seu
    próprio AgentRun (as tools chamadas aqui exigem um já aberto)."""

    logger.info("Operational Memory: iniciando recall para order_id=%s", context.orderId)
    agent_run = audit.start_agent_run(context, AgentName.OPERATIONAL_MEMORY)

    snapshot = tools.get_customer_memory(context.customer.id, agent_run=agent_run)

    memory_context = _recall_from_approved_memory(context, snapshot)
    result = AgentResult(agent=AgentName.OPERATIONAL_MEMORY, status=AgentStatus.OK, data=memory_context)
    audit.finish_agent_run(agent_run, next_state="validating", result=result)
    return result


def propose(
    context: OrderContext,
    *,
    observed: str,
    resolved_sku: str,
    evidence_quote: str,
    conversation_ref: str,
    source_order_version_id: int | None = None,
) -> AgentResult:
    """Registra o alias que acabou de ser confirmado pelo cliente como uma
    `MemoryProposal` — sempre `pending_review` (guardrail #5 do
    CLAUDE.md). Não usa LLM: quem chama já sabe o que foi confirmado
    (Validation resolveu o SKU, o cliente confirmou o texto); esta função
    só persiste isso com evidência rastreável.

    Nota: ainda não está encaixada em nenhum gatilho do orchestrator.py —
    o AGENTS_PLAN.md diz que ela roda depois do pedido ir pro ERP, mas
    isso não faz parte da tabela de transições implementada. Fica
    disponível pra ser chamada quando essa decisão for tomada.
    """

    agent_run = audit.start_agent_run(context, AgentName.OPERATIONAL_MEMORY)

    # O retorno (a linha criada em apps.core.models.MemoryProposal) não
    # precisa ser usado aqui — quem revisa a proposta depois consulta o
    # banco diretamente. O que este agente devolve é o schemas.MemoryProposal,
    # o formato de saída do agente (ver AgentResult), não o registro do ORM.
    tools.create_memory_proposal(
        context.customer.id,
        observed,
        resolved_sku,
        evidence_quote,
        agent_run=agent_run,
        source_order_version_id=source_order_version_id,
    )

    proposal = MemoryProposal(
        customerId=str(context.customer.id),
        observed=observed,
        resolvedSku=resolved_sku,
        evidence={
            "source": "customer_confirmation",
            "conversationRef": conversation_ref,
            "quote": evidence_quote,
        },
    )

    result = AgentResult(agent=AgentName.OPERATIONAL_MEMORY, status=AgentStatus.OK, data=proposal)
    audit.finish_agent_run(
        agent_run,
        next_state=context.state.value,
        result=result,
    )
    return result
