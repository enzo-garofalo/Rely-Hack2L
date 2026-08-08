"""ERP Execution Agent (G5): cria o pedido aprovado no ERP simulado.

Mecânico — checa pré-condições, monta o payload, chama a tool
idempotente. Sem LLM: não há nada a interpretar aqui, só executar
(AGENTS_PLAN.md, coluna "modelo sugerido": "um único tool call, modelo
médio basta" — na prática nem precisa de modelo algum).
"""

from __future__ import annotations

import logging

from . import audit, tools
from .context import OrderContext
from .schemas import AgentName, AgentResult, AgentStatus, ErpReceipt

logger = logging.getLogger(__name__)


def run(context: OrderContext) -> AgentResult:
    """Assinatura compatível com `orchestrator.AgentRunner`. As
    pré-condições (confirmado + aprovado) já foram checadas pelo
    Supervisor antes de chamar este agente (`operator_approve`), mas
    checamos de novo aqui — este agente não deveria confiar cegamente em
    quem o invocou (guardrail #3 do CLAUDE.md é "não-negociável")."""

    # Sem LLM aqui — o único log deste agente é este mesmo. Sem ele, esta
    # etapa fica muda na visualização em tempo real (que lê logs porque o
    # AgentRun só commita no fim da transação do pedido inteiro).
    logger.info("ERP Execution: iniciando para order_id=%s", context.orderId)
    agent_run = audit.start_agent_run(context, AgentName.ERP_EXECUTION)

    if not (context.approvals.customerConfirmed and context.approvals.operatorApproved):
        result = AgentResult(
            agent=AgentName.ERP_EXECUTION,
            status=AgentStatus.ERROR,
            error="pré-condições não satisfeitas: falta customerConfirmed e/ou operatorApproved",
        )
        audit.finish_agent_run(agent_run, next_state=context.state.value, result=result)
        return result

    if context.ambiguities:
        result = AgentResult(
            agent=AgentName.ERP_EXECUTION,
            status=AgentStatus.ERROR,
            error="há itens ainda ambíguos; não é possível enviar ao ERP",
        )
        audit.finish_agent_run(agent_run, next_state=context.state.value, result=result)
        return result

    quantity_by_ref = {item.id: item.quantity for item in context.items}
    items_payload = [
        {"sku": resolved.sku, "qty": quantity_by_ref[resolved.itemRef]} for resolved in context.resolvedItems
    ]
    # Determinística e estável por pedido: a mesma combinação
    # conversa+order nunca gera duas chaves diferentes, então um retry
    # (timeout, reconexão) sempre cai na mesma Idempotency-Key.
    idempotency_key = f"order-{context.conversationId}-{context.orderId}"

    try:
        erp_order = tools.create_erp_order(
            context.customer.id,
            items_payload,
            context.total or 0.0,
            idempotency_key,
            agent_run=agent_run,
        )
    except Exception as exc:  # falha real do ERP (ex.: banco fora do ar) — nunca vira sucesso silencioso
        result = AgentResult(agent=AgentName.ERP_EXECUTION, status=AgentStatus.ERROR, error=str(exc))
        audit.finish_agent_run(agent_run, next_state="erp_execution_failed", result=result)
        return result

    receipt = ErpReceipt(
        externalOrderId=erp_order.external_order_number,
        idempotencyKey=idempotency_key,
        payload={"customerId": context.customer.id, "items": items_payload, "total": context.total},
    )
    result = AgentResult(agent=AgentName.ERP_EXECUTION, status=AgentStatus.OK, data=receipt)
    audit.finish_agent_run(agent_run, next_state="sent_to_erp", result=result)
    logger.info("ERP Execution: pedido criado no ERP (%s) para order_id=%s", erp_order.external_order_number, context.orderId)
    return result
