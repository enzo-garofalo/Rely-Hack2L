"""Order Intake Agent (G2): transforma a mensagem livre do cliente em
itens estruturados.

Uma única chamada de modelo, sem tools (AGENTS_PLAN.md) — o Intake só
estrutura o que foi dito. Não resolve SKU, não consulta preço/estoque,
não inventa item que não está na mensagem: isso tudo é trabalho do
Validation, mais adiante no pipeline.
"""

from __future__ import annotations

from .context import OrderContext
from .llm_client import LLMOutputError, call_structured
from .schemas import AgentName, AgentResult, AgentStatus, OrderDraft

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
    agente."""

    if not context.messageText.strip():
        return AgentResult(
            agent=AgentName.ORDER_INTAKE,
            status=AgentStatus.ERROR,
            error="context.messageText vazio — nada para estruturar",
        )

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
    except LLMOutputError as exc:
        return AgentResult(agent=AgentName.ORDER_INTAKE, status=AgentStatus.ERROR, error=str(exc))

    return AgentResult(agent=AgentName.ORDER_INTAKE, status=AgentStatus.OK, data=draft)
