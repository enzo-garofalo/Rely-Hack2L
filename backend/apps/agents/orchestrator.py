"""Supervisor: a máquina de estados determinística do Opero.

Princípio central (AGENTS_PLAN.md): orquestração é determinística,
interpretação é LLM. Este módulo NUNCA chama um modelo diretamente e nunca
interpreta texto — só decide o que acontece e quando, chamando o agente
autorizado pra cada etapa. Os agentes não se chamam entre si; toda
coordenação passa por aqui.

Os 4 agentes (intake.py, memory.py, validation.py, erp_execution.py — G2 a
G5) ainda não existem. Por isso o Supervisor recebe as funções `run` dos
agentes injetadas via `Agents`, em vez de importá-las diretamente: dá pra
testar a máquina de estados inteira hoje com stubs, e trocar pelos agentes
reais depois sem mudar uma linha deste arquivo (é literalmente o DoD da
task E6 no PLANO_IMPLEMENTACAO.md).

Persistência de `AgentRun` (auditoria em banco) é responsabilidade do app
`core`, fora do escopo desta pasta — por isso existe o hook opcional
`on_agent_run`, que por padrão não faz nada.
"""

from __future__ import annotations

from typing import Callable

from .context import OrderContext, OrderState
from .schemas import AgentResult, AgentStatus, AmbiguousItem, ResolvedItem, ValidatedOrder

# Assinatura comum aos agentes que só precisam do contexto atual.
AgentRunner = Callable[[OrderContext], AgentResult]

# O Validation Agent recebe um segundo argumento: `itemRef` do item a
# reprocessar, ou None para validar o pedido inteiro (primeira passada).
# Existe como tipo próprio (em vez de reaproveitar AgentRunner) pra deixar
# visível, na assinatura, a regra do Supervisor de que uma resposta de
# esclarecimento reprocessa **um item**, nunca o pedido do zero.
ValidationRunner = Callable[[OrderContext, "str | None"], AgentResult]

# Chamado depois de toda invocação de agente, bem-sucedida ou não — é aqui
# que o app core pluga a gravação de AgentRun no banco, se/quando existir.
AgentRunHook = Callable[[OrderContext, AgentResult], None]


class OrchestratorError(Exception):
    """Um evento foi chamado num estado que não permite essa transição —
    ex.: tentar `operator_approve` antes de `customer_confirm`. É erro de
    uso do Supervisor (guard violado), diferente de um agente que falhou
    (isso vem como `AgentResult` com status=ERROR, não como exceção)."""


class Agents:
    """Bundle das funções `run()` dos 4 agentes, injetadas no Supervisor.
    Enquanto G2-G5 não existem, passe stubs aqui; quando existirem, é só
    trocar o que é passado no construtor — o Supervisor não muda."""

    def __init__(
        self,
        order_intake: AgentRunner,
        operational_memory: AgentRunner,
        validation: ValidationRunner,
        erp_execution: AgentRunner,
    ) -> None:
        self.order_intake = order_intake
        self.operational_memory = operational_memory
        self.validation = validation
        self.erp_execution = erp_execution


class Supervisor:
    """Máquina de estados do AGENTS_PLAN.md. Cada método público
    corresponde a um "gatilho" da tabela de transições — o Supervisor
    nunca avança um pedido sozinho além do que a tabela permite."""

    def __init__(self, agents: Agents, on_agent_run: AgentRunHook | None = None) -> None:
        self._agents = agents
        self._on_agent_run = on_agent_run

    # -- infra interna ------------------------------------------------

    def _run_agent(self, context: OrderContext, result: AgentResult) -> AgentResult:
        """Registra o resultado de uma chamada de agente na trilha de
        auditoria e dispara o hook externo, se houver. Não decide
        transição — quem chama isso é quem sabe o que fazer com sucesso
        ou erro em cada etapa específica."""

        context.record_event(
            "agent_run",
            {"agent": result.agent.value, "status": result.status.value, "error": result.error},
        )
        if self._on_agent_run is not None:
            self._on_agent_run(context, result)
        return result

    def _transition(self, context: OrderContext, to: OrderState) -> None:
        frm = context.state
        context.state = to
        context.record_event("state_transition", {"from": frm.value, "to": to.value})

    def _require_state(self, context: OrderContext, expected: OrderState) -> None:
        if context.state != expected:
            raise OrchestratorError(
                f"esperava estado '{expected.value}', mas o pedido está em '{context.state.value}'"
            )

    def _apply_validation(self, context: OrderContext, validated: ValidatedOrder) -> None:
        """Espalha a saída do Validation Agent pelos campos do contexto.
        Usado tanto na primeira validação quanto no reprocessamento de um
        único item (patch) — nos dois casos o agente devolve o estado
        **completo** e atual do pedido (itens não tocados incluídos), então
        não existe merge manual aqui: é substituição direta."""

        context.resolvedItems = [item for item in validated.items if isinstance(item, ResolvedItem)]
        context.ambiguities = [item for item in validated.items if isinstance(item, AmbiguousItem)]
        # total só existe com o pedido 100% resolvido — nunca um número
        # parcial calculado sobre itens ainda pendentes (guardrail #2).
        context.total = validated.total if validated.is_fully_resolved else None

    def _advance_after_validation(self, context: OrderContext) -> None:
        """validating -> waiting_customer (se sobrou ambiguidade) ou
        ready_for_confirmation (se tudo foi resolvido). Nenhuma ambiguidade
        é resolvida em silêncio (guardrail #6): a presença de qualquer
        item em `context.ambiguities` sempre trava o avanço."""

        if context.ambiguities:
            self._transition(context, OrderState.WAITING_CUSTOMER)
        else:
            self._transition(context, OrderState.READY_FOR_CONFIRMATION)

    # -- eventos --------------------------------------------------------

    def receive_message(self, context: OrderContext, message_text: str) -> AgentResult:
        """received -> parsing -> memory_loaded -> validating -> (waiting_customer | ready_for_confirmation).

        As três primeiras transições rodam em sequência automaticamente:
        nenhuma delas espera input humano, então não faz sentido parar o
        pedido no meio. O fluxo só pausa de fato em `waiting_customer`
        (esclarecimento) ou mais adiante em `pending_approval`.
        """

        self._require_state(context, OrderState.RECEIVED)
        context.messageText = message_text
        context.record_event("message_received", {"message": message_text})
        self._transition(context, OrderState.PARSING)

        intake_result = self._run_agent(context, self._agents.order_intake(context))
        if intake_result.status != AgentStatus.OK:
            # Falha explícita: o pedido fica parado em 'parsing', não
            # avança fingindo que extraiu itens (guardrail #7).
            return intake_result
        context.items = intake_result.data.items
        context.deliveryDate = intake_result.data.deliveryDate

        self._transition(context, OrderState.MEMORY_LOADED)

        # Memory (recall) é opcional por definição (AGENTS_PLAN.md): se
        # falhar, isso NÃO bloqueia o fluxo — só seguimos sem hints. É a
        # única etapa do pipeline automático com essa tolerância; todas
        # as outras interrompem o avanço em caso de erro.
        memory_result = self._run_agent(context, self._agents.operational_memory(context))
        if memory_result.status == AgentStatus.OK:
            context.hints = memory_result.data.hints
        else:
            context.hints = []

        self._transition(context, OrderState.VALIDATING)

        validation_result = self._run_agent(context, self._agents.validation(context, None))
        if validation_result.status != AgentStatus.OK:
            return validation_result

        self._apply_validation(context, validation_result.data)
        self._advance_after_validation(context)
        return validation_result

    def customer_reply(self, context: OrderContext, item_ref: str, message: str) -> AgentResult:
        """waiting_customer -> validating -> (waiting_customer | ready_for_confirmation).

        Guard crítico do AGENTS_PLAN.md: em `waiting_customer`, só input do
        cliente destrava — por isso este é o único método que aceita sair
        desse estado. E a resposta reprocessa **apenas** `item_ref` (patch),
        nunca o pedido inteiro do zero: é por isso que `item_ref` é
        obrigatório e passado direto pro Validation Agent.
        """

        self._require_state(context, OrderState.WAITING_CUSTOMER)

        # A mensagem do cliente vira parte da trilha de auditoria; é dali
        # que o Validation Agent lê o que foi respondido para este item
        # (o contrato exato de "como o agente enxerga essa resposta" é
        # decisão de implementação do G4, não deste módulo).
        context.record_event("customer_reply", {"itemRef": item_ref, "message": message})

        self._transition(context, OrderState.VALIDATING)

        validation_result = self._run_agent(context, self._agents.validation(context, item_ref))
        if validation_result.status != AgentStatus.OK:
            return validation_result

        self._apply_validation(context, validation_result.data)
        self._advance_after_validation(context)
        return validation_result

    def customer_confirm(self, context: OrderContext) -> None:
        """ready_for_confirmation -> customer_confirmed -> pending_approval.

        As duas transições andam juntas porque a tabela do AGENTS_PLAN.md
        não tem gatilho algum entre `customer_confirmed` e
        `pending_approval` ("—") — ou seja, uma segue a outra sem esperar
        mais nada. Não chama agente: confirmação de resumo não precisa de
        LLM nem de tool.
        """

        self._require_state(context, OrderState.READY_FOR_CONFIRMATION)
        context.approvals.customerConfirmed = True
        self._transition(context, OrderState.CUSTOMER_CONFIRMED)
        self._transition(context, OrderState.PENDING_APPROVAL)

    def operator_approve(self, context: OrderContext) -> AgentResult:
        """pending_approval -> sending_to_erp -> (sent_to_erp | erp_execution_failed).

        Guard não-negociável (guardrail #3 do CLAUDE.md e do
        AGENTS_PLAN.md): nenhuma escrita no ERP antes de
        `customerConfirmed` **e** `operatorApproved`, os dois juntos. O
        `_require_state` já garante que só chegamos aqui vindo de
        `pending_approval` (que por sua vez só é alcançado depois de
        `customer_confirm`), mas o check explícito de `approvals` fica
        aqui mesmo assim — é o guard mais importante do sistema pra
        depender só da ordem das chamadas.
        """

        self._require_state(context, OrderState.PENDING_APPROVAL)
        if not (context.approvals.customerConfirmed):
            raise OrchestratorError("operator_approve chamado sem customerConfirmed=True")

        context.approvals.operatorApproved = True
        self._transition(context, OrderState.SENDING_TO_ERP)

        erp_result = self._run_agent(context, self._agents.erp_execution(context))
        if erp_result.status != AgentStatus.OK:
            # Falha na escrita do ERP é um estado terminal explícito, não
            # um retorno silencioso a um estado anterior — a UI precisa
            # mostrar que isso quebrou (guardrail #7).
            self._transition(context, OrderState.ERP_EXECUTION_FAILED)
            return erp_result

        context.erpReceipt = erp_result.data
        self._transition(context, OrderState.SENT_TO_ERP)
        return erp_result
