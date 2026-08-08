"""Order Intake Agent (G2): transforma a mensagem livre do cliente em
itens estruturados.

Uma única chamada de modelo, sem tools (AGENTS_PLAN.md) — o Intake só
estrutura o que foi dito. Não resolve SKU, não consulta preço/estoque,
não inventa item que não está na mensagem: isso tudo é trabalho do
Validation, mais adiante no pipeline.
"""

from __future__ import annotations

import logging

from . import audit
from .context import OrderContext
from .llm_client import LLMOutputError, call_structured
from .schemas import AgentName, AgentResult, AgentStatus, OrderDraft

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Você estrutura pedidos de um cliente B2B a partir de uma mensagem livre "
    "de WhatsApp. Extraia cada item pedido, preservando o texto original "
    "exato de cada um em rawText. Não resolva SKU (deixe null), não invente "
    "item que não foi mencionado na mensagem, não calcule preço ou total. "
    "Se faltar alguma informação (ex.: data de entrega), liste em "
    "missingFields em vez de adivinhar."
)


def run(context: OrderContext) -> AgentResult:
    """Assinatura compatível com `orchestrator.AgentRunner`: só recebe o
    `OrderContext`. O texto a estruturar é `context.messageText`, já
    colocado lá pelo Supervisor em `receive_message` antes de chamar este
    agente.

    Abre seu próprio `AgentRun` (RF37: toda execução de agente gera um
    registro), mesmo nos caminhos de erro — mesmo padrão de memory.py,
    validation.py e erp_execution.py."""

    agent_run = audit.start_agent_run(context, AgentName.ORDER_INTAKE)

    logger.info("Order Intake: iniciando para order_id=%s", context.orderId)

    if not context.messageText.strip():
        result = AgentResult(
            agent=AgentName.ORDER_INTAKE,
            status=AgentStatus.ERROR,
            error="context.messageText vazio — nada para estruturar",
        )
        audit.finish_agent_run(agent_run, next_state=context.state.value, result=result)
        return result

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": context.messageText},
    ]

    try:
        draft = call_structured(
            agent=AgentName.ORDER_INTAKE,
            messages=messages,
            output_schema=OrderDraft,
        )
    except (LLMOutputError, RuntimeError) as exc:
        # RuntimeError também aqui: get_client()/get_model_for_agent (dentro
        # de call_structured) falham assim quando a config do LLM está
        # incompleta (ex.: FEATHERLESS_API_KEY ausente) — sem capturar isso,
        # o AgentRun aberto acima nunca fecha (fica com success=True por
        # default e finished_at nulo), o que é pior que o erro em si
        # (guardrail #7 do CLAUDE.md: falha nunca vira sucesso por
        # inferência — nem por omissão).
        result = AgentResult(agent=AgentName.ORDER_INTAKE, status=AgentStatus.ERROR, error=str(exc))
        audit.finish_agent_run(agent_run, next_state=context.state.value, result=result)
        return result

    result = AgentResult(agent=AgentName.ORDER_INTAKE, status=AgentStatus.OK, data=draft)
    audit.finish_agent_run(agent_run, next_state="memory_loaded", result=result)
    return result
