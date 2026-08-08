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

import json
from dataclasses import asdict

from . import audit, tools
from .context import OrderContext
from .schemas import AgentName, AgentResult, AgentStatus, MemoryContext, MemoryProposal
from .llm_client import LLMOutputError, call_structured

_SYSTEM_PROMPT = (
    "Você é um consultor de memória para um sistema de pedidos B2B. Recebe os "
    "itens do pedido atual e o histórico real do cliente (aliases confirmados, "
    "preferências, pedidos recentes no ERP). Para cada item atual que pode se "
    "beneficiar do histórico, gere um hint com o campo sugerido, o valor, uma "
    "confiança de 0 a 1 e a evidência exata que sustenta a sugestão. NUNCA "
    "sugira um SKU que não apareça no histórico fornecido — você não tem acesso "
    "ao catálogo, só está lembrando o que já foi visto antes. Se nada do "
    "histórico ajuda, devolva hints e preferences vazios."
)


def run(context: OrderContext) -> AgentResult:
    """Assinatura compatível com `orchestrator.AgentRunner`. Cria seu
    próprio AgentRun (as tools chamadas aqui exigem um já aberto)."""

    agent_run = audit.start_agent_run(context, AgentName.OPERATIONAL_MEMORY)

    snapshot = tools.get_customer_memory(context.customer.id, agent_run=agent_run)

    if not snapshot.aliases and not snapshot.preferences and not snapshot.recentOrders:
        # Recall é opcional por definição (AGENTS_PLAN.md): sem histórico
        # nenhum, nem vale chamar o modelo — devolve vazio e segue.
        result = AgentResult(agent=AgentName.OPERATIONAL_MEMORY, status=AgentStatus.OK, data=MemoryContext())
        audit.finish_agent_run(agent_run, next_state=context.state.value, result=result)
        return result

    user_payload = {
        "currentItems": [
            {"id": item.id, "productGuess": item.productGuess, "rawText": item.rawText}
            for item in context.items
        ],
        "history": {
            "aliases": [asdict(a) for a in snapshot.aliases],
            "preferences": [asdict(p) for p in snapshot.preferences],
            "recentOrders": [
                {"externalOrderNumber": o.externalOrderNumber, "items": o.items, "createdAt": o.createdAt.isoformat()}
                for o in snapshot.recentOrders
            ],
        },
    }

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]

    try:
        memory_context = call_structured(
            agent=AgentName.OPERATIONAL_MEMORY,
            messages=messages,
            output_schema=MemoryContext,
        )
    except LLMOutputError as exc:
        result = AgentResult(agent=AgentName.OPERATIONAL_MEMORY, status=AgentStatus.ERROR, error=str(exc))
        audit.finish_agent_run(agent_run, next_state=context.state.value, result=result)
        return result

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
