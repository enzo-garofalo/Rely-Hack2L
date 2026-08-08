"""OrderContext: o objeto único que os 4 agentes leem e o Supervisor
escreve. Não existe troca de mensagem direta entre agentes — tudo que um
agente precisa saber sobre o pedido em construção está aqui, e tudo que
ele produz volta pra cá através do Supervisor (AGENTS_PLAN.md, seção
"Objeto compartilhado: OrderContext").

É uma dataclass (não um schema Pydantic) de propósito: diferente dos
schemas.py, o OrderContext não é validado contra saída de LLM — é estado
interno do processo, mutado pelo orquestrador. Pydantic entra onde tem
fronteira com o modelo; dataclass entra onde é só estado nosso.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any

from .schemas import AmbiguousItem, ErpReceipt, MemoryHint, OrderItemDraft, ResolvedItem


class OrderState(str, Enum):
    """Os estados da máquina do Supervisor (AGENTS_PLAN.md, tabela de
    transições). `ERP_EXECUTION_FAILED` é o único estado terminal de erro
    — existe pra que uma falha na escrita do ERP apareça explicitamente
    no contexto, em vez de travar em `sending_to_erp` para sempre ou
    fingir que virou `sent_to_erp` (guardrail #7 do CLAUDE.md: falha
    nunca vira sucesso por inferência)."""

    RECEIVED = "received"  # mensagem chegou, nada foi processado ainda
    PARSING = "parsing"  # Order Intake está estruturando a mensagem em itens
    MEMORY_LOADED = "memory_loaded"  # Operational Memory (recall) rodou — ou foi pulado, é opcional
    VALIDATING = "validating"  # Validation está resolvendo itens contra o catálogo/ERP
    WAITING_CUSTOMER = "waiting_customer"  # há ambiguidade aberta; só aceita resposta do cliente, nada mais destrava
    READY_FOR_CONFIRMATION = "ready_for_confirmation"  # tudo resolvido, falta o cliente confirmar o resumo
    CUSTOMER_CONFIRMED = "customer_confirmed"  # cliente confirmou o resumo do pedido
    PENDING_APPROVAL = "pending_approval"  # falta aprovação humana do operador antes de tocar no ERP
    SENDING_TO_ERP = "sending_to_erp"  # ERP Execution está chamando create_erp_order (com Idempotency-Key)
    SENT_TO_ERP = "sent_to_erp"  # pedido criado de fato no ERP — system of record atualizado
    ERP_EXECUTION_FAILED = "erp_execution_failed"  # escrita no ERP falhou; fica visível, não é escondida nem reinterpretada como sucesso


@dataclass
class CustomerRef:
    """Identificação mínima do cliente dentro do contexto. Só o essencial
    pra rotear e exibir — dados comerciais do cliente (histórico, etc.)
    vêm de tools, não ficam duplicados aqui."""

    id: str
    phone: str


@dataclass
class Approvals:
    """As duas travas que **juntas** liberam a escrita no ERP (guardrail
    #3 do CLAUDE.md: "aprovação humana antes de qualquer escrita no
    ERP... na mesma versão"). O Supervisor só chama o ERP Execution Agent
    quando ambos os campos estiverem True — nenhum agente decide isso
    sozinho."""

    customerConfirmed: bool = False  # cliente confirmou o resumo do pedido (estado customer_confirmed)
    operatorApproved: bool = False  # operador humano aprovou na interface (estado pending_approval -> sending_to_erp)


@dataclass
class OrderEvent:
    """Uma linha da trilha de auditoria: uma tool call ou uma transição de
    estado. É o que alimenta a timeline de agentes na interface e serve de
    evidência para a banca — se não está registrado aqui, não aconteceu
    (AGENTS_PLAN.md, campo `events`)."""

    type: str  # ex.: "state_transition", "tool_call", "agent_error"
    payload: dict[str, Any]  # detalhes do evento (de/para do estado, nome da tool, argumentos, resultado, etc.)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class OrderContext:
    """O estado completo de um pedido em construção, do recebimento da
    mensagem até a criação no ERP (ou falha). Cada agente recebe este
    objeto, lê só o que precisa, e devolve um AgentResult (schemas.py)
    que o Supervisor usa para atualizar os campos abaixo — o agente nunca
    edita o OrderContext diretamente."""

    conversationId: str  # id da conversa de origem (WhatsApp) — chave que amarra este pedido à trilha de mensagens no app core
    customer: CustomerRef  # quem está fazendo o pedido
    state: OrderState = OrderState.RECEIVED  # estado atual da máquina do Supervisor

    deliveryDate: date | None = None  # data de entrega, extraída pelo Intake ou confirmada depois

    items: list[OrderItemDraft] = field(default_factory=list)  # itens estruturados (saída do Intake) — rascunho, sem SKU/preço confirmados
    hints: list[MemoryHint] = field(default_factory=list)  # sugestões da memória (recall) — nunca fatos, ver MemoryHint em schemas.py
    resolvedItems: list[ResolvedItem] = field(default_factory=list)  # itens já casados com o catálogo real (sku/preço/estoque) — preenchido pelo Validation
    ambiguities: list[AmbiguousItem] = field(default_factory=list)  # itens ainda bloqueados esperando esclarecimento do cliente

    total: float | None = None  # só preenchido quando calculate_total roda sobre itens 100% resolvidos (guardrail #2 do CLAUDE.md)
    approvals: Approvals = field(default_factory=Approvals)  # as duas confirmações que liberam a escrita no ERP

    erpReceipt: ErpReceipt | None = None  # preenchido só depois que o ERP Execution Agent cria o pedido de verdade

    events: list[OrderEvent] = field(default_factory=list)  # log cronológico de tudo que aconteceu neste pedido — auditoria e timeline da UI

    def record_event(self, type: str, payload: dict[str, Any]) -> None:
        """Acrescenta um evento à trilha de auditoria. Só isso — decidir
        *quando* chamar (após uma tool call, após uma transição) é
        responsabilidade do orchestrator.py, não deste objeto. Manter essa
        função aqui, e não a lógica de transição, é o que preserva a regra
        de que orquestração é determinística e mora só no Supervisor."""

        self.events.append(OrderEvent(type=type, payload=payload))
