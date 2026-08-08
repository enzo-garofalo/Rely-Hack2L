"""Contratos congelados de entrada/saída dos agentes.

Fonte da verdade: ../AGENTS_PLAN.md. Se este arquivo divergir do plano,
alinhe os dois antes de mexer em qualquer agente — mudanças aqui afetam
orchestrator.py e o consumo no frontend (CLAUDE.md, seção "Ao fazer
mudanças").
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Envelope comum a todo agente
# ---------------------------------------------------------------------------


class AgentName(str, Enum):
    """Identifica qual dos 4 agentes gerou um AgentResult. Usado no
    registro de auditoria (AgentRun, no app core) e em logs — sem isso,
    não dá pra saber quem fez o quê olhando só o objeto de saída."""

    ORDER_INTAKE = "order_intake"
    OPERATIONAL_MEMORY = "operational_memory"
    VALIDATION = "validation"
    ERP_EXECUTION = "erp_execution"


class AgentStatus(str, Enum):
    """OK ou ERROR, nada de meio-termo. Existe pra impedir exatamente o
    guardrail #7 do CLAUDE.md: 'falha nunca vira sucesso por inferência'.
    O orquestrador decide a transição de estado olhando pra este campo,
    não tentando adivinhar se `data` "parece" válido."""

    OK = "ok"
    ERROR = "error"


# AgentResult é definido no final do arquivo: seu campo `data` é uma união
# discriminada de todos os schemas abaixo, então só pode existir depois
# que eles estiverem declarados (ver comentário perto da definição).


# ---------------------------------------------------------------------------
# Order Intake Agent
# ---------------------------------------------------------------------------


class OrderItemDraft(BaseModel):
    """Um item exatamente como o cliente descreveu, ainda sem passar pelo
    catálogo. O Intake só estrutura o texto — resolver SKU é trabalho do
    Validation, então aqui `sku` normalmente é None."""

    id: str  # ex: "item-1" — referência estável usada por Memory/Validation pra apontar de volta pra este item
    rawText: str  # trecho literal da mensagem que originou o item — preserva a evidência original, nunca reescreva
    productGuess: str  # nome do produto como o modelo entendeu (ex: "coca 2L"), ainda não é um SKU
    quantity: float  # quantidade informada pelo cliente, tal como veio (a unidade separada no campo abaixo)
    unit: str  # unidade informada (ex: "caixa", "fardo", "unidade") — ainda em linguagem do cliente, não do catálogo
    sku: str | None = None  # normalmente None aqui; Intake não resolve SKU (guardrail: "não resolve SKU, não inventa item")
    ambiguities: list[str] = Field(default_factory=list)  # pontos que o próprio Intake já percebeu como incertos neste item


class OrderDraft(BaseModel):
    """Saída do Order Intake Agent: a conversa livre virou uma lista de
    itens estruturados. Ainda não tem preço, estoque nem SKU confirmado —
    isso é tarefa do Validation, mais adiante no fluxo."""

    kind: Literal["order_draft"] = "order_draft"  # discriminador fixo — é o que permite reconstruir o tipo certo de dentro de AgentResult.data
    items: list[OrderItemDraft]
    deliveryDate: date | None = None  # data de entrega extraída da mensagem, se o cliente mencionou
    missingFields: list[str] = Field(default_factory=list)  # o que faltou na mensagem (ex: sem data de entrega) — não é inventado depois, é perguntado
    evidence: list[str] = Field(default_factory=list)  # trechos literais que embasam a extração como um todo, além do rawText por item


# ---------------------------------------------------------------------------
# Operational Memory Agent — recall (leitura)
# ---------------------------------------------------------------------------


class MemoryHintSuggestion(BaseModel):
    """O palpite em si: qual campo do item a memória está sugerindo
    preencher e com qual valor. Separado do resto do hint pra deixar
    claro que isso é *sugestão*, não fato confirmado."""

    field: str  # nome do campo sugerido (ex: "sku")
    value: str  # valor sugerido pra esse campo (ex: um SKU do catálogo)


class MemoryHint(BaseModel):
    """Uma pista da memória histórica sobre um item específico do pedido.
    Guardrail central do Memory Agent: 'sugere, nunca afirma' — por isso
    todo hint carrega `evidence` e `confidence`. Sem evidência rastreável,
    o hint não deveria nem existir (ver AGENTS_PLAN.md)."""

    itemRef: str  # aponta para o `id` do OrderItemDraft a que este hint se refere
    type: str  # tipo do hint (ex: "alias_resolution") — deixado como string livre pra não travar tipos futuros
    suggests: MemoryHintSuggestion  # o palpite (campo + valor)
    confidence: float = Field(ge=0.0, le=1.0)  # 0 a 1; confiança baixa não fecha o item sozinha, vira pergunta de esclarecimento
    evidence: str  # por que a memória sugere isso (ex: "cliente comprou X nos últimos 3 pedidos") — obrigatório, nunca inventado
    status: Literal["suggestion"] = "suggestion"  # fixo em "suggestion": um hint nunca nasce como fato confirmado


class MemoryPreference(BaseModel):
    """Preferência observada do cliente que não é sobre um item específico
    (ex: janela de entrega preferida). Mesma regra dos hints: sempre com
    evidência, nunca afirmada como certeza absoluta."""

    type: str  # tipo da preferência (ex: "delivery_window")
    value: str  # valor observado (ex: "manhã")
    evidence: str  # base histórica que sustenta a preferência (ex: "últimas 5 entregas aceitas pela manhã")


class MemoryContext(BaseModel):
    """Saída da operação `recall` do Memory Agent — leitura opcional que
    roda durante o intake. Se nada no histórico ajuda, ambas as listas
    vêm vazias e o fluxo segue sem travar (recall nunca é obrigatório)."""

    kind: Literal["memory_context"] = "memory_context"  # discriminador — distingue de MemoryProposal dentro de AgentResult.data
    hints: list[MemoryHint] = Field(default_factory=list)
    preferences: list[MemoryPreference] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Operational Memory Agent — propose (escrita, pending_review sempre)
# ---------------------------------------------------------------------------


class MemoryProposalEvidence(BaseModel):
    """De onde veio a confirmação que originou esta proposta de memória.
    Existe pra que qualquer aprendizado seja auditável depois — dá pra
    voltar na conversa exata e conferir que o cliente realmente confirmou
    aquilo."""

    source: str  # origem da evidência (ex: "customer_confirmation")
    conversationRef: str  # referência à mensagem específica (ex: "msg-7")
    quote: str  # citação literal do cliente confirmando o alias


class MemoryProposal(BaseModel):
    """Saída da operação `propose` do Memory Agent. Roda só depois que o
    cliente confirma um esclarecimento — por exemplo, "fardo da zero" foi
    confirmado como um SKU específico. Isso NUNCA vira um alias confiável
    automaticamente: nasce `pending_review` e alguém humano aprova depois
    (guardrail #5 do CLAUDE.md: "memória não substitui o ERP")."""

    kind: Literal["memory_proposal"] = "memory_proposal"  # discriminador — distingue de MemoryContext dentro de AgentResult.data
    customerId: str  # cliente a quem este alias pertence — aprendizado é por cliente, não global
    type: Literal["alias"] = "alias"  # por ora só existe esse tipo de proposta (observado -> SKU)
    observed: str  # como o cliente se referiu ao produto (ex: "fardo da zero")
    resolvedSku: str  # SKU que o Validation confirmou como correspondente, com o catálogo real
    status: Literal["pending_review"] = "pending_review"  # sempre nasce assim; nunca é setado como aprovado por aqui
    evidence: MemoryProposalEvidence  # rastro da conversa que sustenta a proposta


# ---------------------------------------------------------------------------
# Validation Agent
# ---------------------------------------------------------------------------


class ResolvedItem(BaseModel):
    """Um item que o Validation conseguiu casar 100% com o catálogo real.
    Todo valor aqui veio de uma tool call contra o ERP simulado — nenhum
    campo é chute do modelo (guardrail: "aceita somente SKUs retornados
    pelo catálogo")."""

    itemRef: str  # aponta de volta para o `id` do item original
    status: Literal["resolved"] = "resolved"
    sku: str  # SKU real, devolvido por search_catalog — nunca inventado
    unit: str  # unidade de venda conforme o catálogo (ex: "caixa com 6"), não a unidade informal do cliente
    unitPrice: float  # preço unitário devolvido por get_price
    inStock: bool  # resultado de check_inventory no momento da validação


class Ambiguity(BaseModel):
    """Um ponto específico de dúvida dentro de um item — geralmente qual
    SKU corresponde ao que o cliente pediu. A pergunta já vem pronta,
    porque é o Validation quem tem o contexto do catálogo pra formulá-la
    (o cliente não deveria receber uma pergunta genérica)."""

    field: str  # qual campo está ambíguo (ex: "sku")
    question: str  # pergunta pronta para mandar ao cliente, já formulada com dados reais
    candidates: list[str]  # SKUs candidatos que o catálogo realmente retornou — nunca uma lista inventada


class AmbiguousItem(BaseModel):
    """Um item que o Validation NÃO conseguiu resolver sozinho. Bloqueia
    o pedido nesse item específico até o cliente responder — nunca é
    resolvido em silêncio (guardrail #6 do CLAUDE.md)."""

    itemRef: str
    status: Literal["ambiguous"] = "ambiguous"
    ambiguities: list[Ambiguity]  # pode haver mais de um campo ambíguo no mesmo item


# Um item validado é ou totalmente resolvido, ou ambíguo — nunca os dois
# nem nenhum dos dois. `discriminator="status"` é explícito de propósito:
# sem ele, o Pydantic usa "smart union" (tenta cada tipo e fica com o que
# validar) — funciona na maioria dos casos, mas com schemas parecidos e
# vindos de round-trip (dict -> model -> dict -> model) já vimos ele
# escolher o tipo errado. Discriminador remove a ambiguidade de vez.
ValidatedItem = Annotated[Union[ResolvedItem, AmbiguousItem], Field(discriminator="status")]


class ValidatedOrder(BaseModel):
    """Saída principal do Validation Agent: a lista de itens, cada um já
    resolvido ou marcado como ambíguo. `total` só é preenchido quando TODO
    item está `resolved` — e mesmo assim é sempre resultado de
    `calculate_total` (função pura em Python), nunca de um número que o
    modelo "calculou" em texto livre (guardrail #2 do CLAUDE.md)."""

    kind: Literal["validated_order"] = "validated_order"  # discriminador dentro de AgentResult.data
    items: list[ValidatedItem]
    total: float | None = None

    @property
    def is_fully_resolved(self) -> bool:
        """Atalho pra saber se dá pra avançar para `ready_for_confirmation`
        ou se ainda existe pendência bloqueando o fluxo em `waiting_customer`."""
        return all(item.status == "resolved" for item in self.items)


class ClarificationRequest(BaseModel):
    """Recorte só com os itens ainda ambíguos — é o que o Supervisor usa
    para popular o estado `waiting_customer` e mandar a pergunta ao
    cliente. Depois que o cliente responde, apenas o item referenciado é
    reprocessado (patch), nunca o pedido inteiro do zero (regra do
    Supervisor no AGENTS_PLAN.md)."""

    kind: Literal["clarification_request"] = "clarification_request"  # discriminador dentro de AgentResult.data
    ambiguousItems: list[AmbiguousItem]


# ---------------------------------------------------------------------------
# ERP Execution Agent
# ---------------------------------------------------------------------------


class ErpReceipt(BaseModel):
    """Saída do ERP Execution Agent após criar o pedido de verdade no ERP
    simulado. Só deveria existir depois que o Supervisor checou as duas
    pré-condições (cliente confirmou E operador aprovou) — o agente em si
    não é a fonte da verdade, o ERP é (guardrail do CLAUDE.md)."""

    kind: Literal["erp_receipt"] = "erp_receipt"  # discriminador dentro de AgentResult.data
    externalOrderId: str  # número do pedido gerado pelo ERP — é esse id que vira o "system of record"
    status: Literal["sent_to_erp"] = "sent_to_erp"
    idempotencyKey: str  # a mesma chave usada na chamada create_erp_order; permite auditar que não houve duplicidade
    payload: dict  # o corpo exato que foi enviado ao ERP, guardado para auditoria/replay


# ---------------------------------------------------------------------------
# Envelope comum a todo agente
# ---------------------------------------------------------------------------
#
# Definido aqui embaixo (e não junto com AgentName/AgentStatus, lá em cima)
# porque `data` precisa enxergar todos os schemas acima para montar a união
# discriminada. `discriminator="kind"` é o que resolve o bug de round-trip:
# cada schema carrega seu próprio literal `kind`, então desserializar um
# dict de volta em AgentResult sempre reconstrói o tipo certo — sem
# depender do Pydantic "adivinhar" por tentativa e erro entre schemas
# parecidos.

AgentData = Annotated[
    Union[
        OrderDraft,
        MemoryContext,
        MemoryProposal,
        ValidatedOrder,
        ClarificationRequest,
        ErpReceipt,
    ],
    Field(discriminator="kind"),
]


class AgentResult(BaseModel):
    """Toda função `run()` de agente devolve um AgentResult — nunca o
    schema específico "pelado". Isso dá ao orquestrador uma forma única
    de checar sucesso/erro antes de decidir a próxima transição, sem
    precisar conhecer o formato interno de cada agente.

    Contrato do envelope: se `status` é OK, `data` vem preenchido com um
    dos schemas acima (o formato depende de qual agente rodou) e `error`
    é None. Se `status` é ERROR, `data` é None e `error` traz uma mensagem
    legível — a falha é explícita, não escondida (guardrail #7).
    """

    agent: AgentName
    status: AgentStatus
    data: AgentData | None = None
    error: str | None = None
