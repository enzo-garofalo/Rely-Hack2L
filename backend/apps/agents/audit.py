"""Ciclo de vida do AgentRun (RF37) — a auditoria "execução de um agente".

Existe como módulo separado de tools.py de propósito: tools.py são as
ferramentas de negócio que os agentes chamam (search_catalog, etc.);
audit.py é infraestrutura de bookkeeping em torno da execução do agente
em si. `ToolCall.agent_run` é uma FK obrigatória (apps/core/models.py) —
ou seja, um AgentRun precisa existir ANTES de qualquer tool ser chamada,
não depois. Por isso cada agente (intake.py, memory.py, validation.py,
erp_execution.py) abre o AgentRun no início do próprio `run()` e fecha no
fim, em vez do orchestrator.py fazer isso — o Supervisor continua sem
tocar em banco (AGENTS_PLAN.md: orquestração é determinística e vive só
em memória; persistência é decisão de cada agente sobre sua própria
execução).
"""

from __future__ import annotations

from django.utils import timezone

from apps.core.models import AgentRun

from .context import OrderContext
from .sanitize import sanitize
from .schemas import AgentName, AgentResult, AgentStatus

# AgentRun.Agent usa "memory" para o Operational Memory Agent, enquanto
# schemas.AgentName usa "operational_memory" — os dois vocabulários
# nasceram em branches diferentes (core vs agents) e não foram unificados.
# Este mapa existe só pra não forçar nenhum dos dois lados a mudar um
# nome já em uso.
_AGENT_RUN_NAME: dict[AgentName, str] = {
    AgentName.ORDER_INTAKE: AgentRun.Agent.ORDER_INTAKE,
    AgentName.OPERATIONAL_MEMORY: AgentRun.Agent.MEMORY,
    AgentName.VALIDATION: AgentRun.Agent.VALIDATION,
    AgentName.ERP_EXECUTION: AgentRun.Agent.ERP_EXECUTION,
}


def start_agent_run(context: OrderContext, agent: AgentName) -> AgentRun:
    """Abre o registro antes do agente rodar. `context.orderId` é o
    `Order` real no banco que este `OrderContext` espelha — sem ele não
    dá pra satisfazer a FK obrigatória de AgentRun."""

    return AgentRun.objects.create(
        order_id=context.orderId,
        agent_name=_AGENT_RUN_NAME[agent],
        previous_state=context.state.value,
    )


def finish_agent_run(agent_run: AgentRun, *, next_state: str, result: AgentResult) -> None:
    """Fecha o registro com o resultado do agente. `next_state` é o
    estado que o próprio agente calculou como consequência do seu
    resultado (ex.: Validation decide "waiting_customer" vs
    "ready_for_confirmation" antes de devolver) — é informativo para a
    timeline de auditoria; quem de fato aplica a transição no
    `OrderContext` é sempre o Supervisor, nunca este módulo."""

    agent_run.next_state = next_state
    agent_run.success = result.status == AgentStatus.OK
    agent_run.reason = sanitize(result.error or "")
    agent_run.output_summary = sanitize(result.model_dump(mode="json")) if result.data is not None else {}
    agent_run.finished_at = timezone.now()
    agent_run.save(update_fields=["next_state", "success", "reason", "output_summary", "finished_at"])
