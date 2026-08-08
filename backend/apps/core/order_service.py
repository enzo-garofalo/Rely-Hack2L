"""Ponte entre o Order API (E7) e a máquina de estados dos agentes
(apps.agents). `OrderContext` só existe em memória durante uma requisição
(agents/context.py) — este módulo reconstrói o contexto a partir do banco
no início de cada ação (`build_context`) e persiste o resultado no fim
(`_persist_context`), para que uma segunda requisição (customer-reply,
confirm, approve) continue de onde a anterior parou.

Volatilidade dos dois lados, de propósito:
- `apps.agents` (orchestrator, context, schemas) é contrato congelado —
  este módulo NUNCA muda esses arquivos, só os consome.
- Persistência em `OrderVersion`/`OrderItem`/`CustomerConfirmation`/
  `OperatorApproval` é responsabilidade deste app (core), como já
  documentado em orchestrator.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import unicodedata

from django.core.management import call_command
from django.db import transaction
from django.db.models import Max

from apps.agents import erp_execution, intake, memory, validation
from apps.agents.context import Approvals, CustomerRef, OrderContext, OrderState
from apps.agents.orchestrator import Agents, OrchestratorError, Supervisor
from apps.agents.schemas import (
    AgentName,
    AgentResult,
    AgentStatus,
    AmbiguousItem,
    ErpReceipt,
    MemoryHint,
    OrderItemDraft,
    ResolvedItem,
)

from . import whatsapp
from .models import (
    AgentRun,
    Conversation,
    Customer,
    CustomerConfirmation,
    Message,
    OperatorApproval,
    Order,
    OrderItem,
    OrderVersion,
)


class OrderServiceError(Exception):
    """Uso inválido da API para o estado atual do pedido (ex.: aprovar sem
    confirmação, responder esclarecimento sem pendência). Engloba
    `OrchestratorError` (guard do Supervisor) e guardas próprias deste
    módulo — quem chama trata as duas da mesma forma (409)."""


@dataclass
class PipelineOutcome:
    """Resultado de uma ação que passa pelo Supervisor. `result` pode vir
    com `status=ERROR` (ex.: LLM falhou) sem que isso seja uma exceção —
    o pedido fica visivelmente parado no estado em que travou (guardrail
    #7 do CLAUDE.md: falha nunca é escondida nem vira sucesso silencioso).
    """

    order: Order
    result: AgentResult


def _agents() -> Agents:
    return Agents(
        order_intake=intake.run,
        operational_memory=memory.run,
        validation=validation.run,
        erp_execution=erp_execution.run,
    )


def _supervisor() -> Supervisor:
    return Supervisor(_agents())


def _run_step(step, agent: AgentName, *args) -> AgentResult:
    """Roda um passo do Supervisor blindado contra exceções inesperadas
    de um agente (ex.: `RuntimeError` de configuração de LLM ausente, que
    intake.py/memory.py/validation.py só tratam parcialmente). Sem isso, um
    erro de configuração vira um 500 cru em vez de um `AgentResult` de
    erro — o guardrail #7 do CLAUDE.md ("falha nunca vira sucesso por
    inferência") pressupõe que a falha aparece, não que ela derruba a
    API. `OrchestratorError` não é capturada aqui: é erro de uso da API
    (guard de transição), tratado por quem chama `_run_step`."""

    try:
        return step(*args)
    except OrchestratorError:
        raise
    except Exception as exc:  # falha inesperada do agente/LLM — nunca deixa a requisição quebrar sem explicação
        return AgentResult(agent=agent, status=AgentStatus.ERROR, error=f"falha inesperada no agente: {exc}")


def build_context(order: Order) -> OrderContext:
    """Reconstrói o `OrderContext` a partir do estado persistido do
    pedido. Sem versão ainda (pedido recém-criado, antes do primeiro
    `receive_message`), devolve o contexto "vazio" no estado atual."""

    context = OrderContext(
        orderId=order.id,
        conversationId=str(order.conversation_id),
        customer=CustomerRef(id=order.customer_id, phone=order.customer.phone),
        state=OrderState(order.state),
    )

    version = order.current_version
    if version is None:
        return context

    snapshot = version.context_snapshot or {}
    context.deliveryDate = version.delivery_date
    context.total = float(version.total) if version.total is not None else None
    context.items = [OrderItemDraft.model_validate(d) for d in snapshot.get("items", [])]
    context.hints = [MemoryHint.model_validate(d) for d in snapshot.get("hints", [])]
    context.resolvedItems = [ResolvedItem.model_validate(d) for d in snapshot.get("resolvedItems", [])]
    context.ambiguities = [AmbiguousItem.model_validate(d) for d in snapshot.get("ambiguities", [])]
    # OneToOne reverso: Django gera uma exceção que também é AttributeError
    # quando não existe linha relacionada, então hasattr() é seguro aqui.
    context.approvals = Approvals(
        customerConfirmed=hasattr(version, "customer_confirmation"),
        operatorApproved=hasattr(version, "operator_approval"),
    )
    erp_receipt = snapshot.get("erpReceipt")
    if erp_receipt:
        context.erpReceipt = ErpReceipt.model_validate(erp_receipt)
    return context


def _intake_extras(order: Order) -> tuple[list[str], list[str]]:
    """`OrderContext` não carrega `missingFields`/`evidence` do
    `OrderDraft` adiante (agents/context.py não tem esses campos) — mas o
    Order Intake Agent já persistiu o próprio `AgentRun.output_summary`
    com o `OrderDraft` completo (audit.py). Em vez de tocar no contrato
    congelado dos agentes, recuperamos os dois campos dali."""

    run = (
        AgentRun.objects.filter(order=order, agent_name=AgentRun.Agent.ORDER_INTAKE, success=True)
        .order_by("-started_at")
        .first()
    )
    if run is None:
        return [], []
    data = run.output_summary.get("data") or {}
    return data.get("missingFields", []), data.get("evidence", [])


def _persist_context(order: Order, context: OrderContext, result: AgentResult) -> None:
    """Grava o `OrderContext` pós-Supervisor de volta no banco. Só cria
    uma `OrderVersion` nova quando o Validation Agent de fato rodou —
    reconhecível porque o resultado veio de `receive_message` ou
    `customer_reply`, nunca de `customer_confirm`/`operator_approve`
    (esses não recriam versão, ver `confirm_customer`/`approve_operator`).
    """

    order.state = context.state.value

    if result.status != AgentStatus.OK:
        order.save(update_fields=["state", "updated_at"])
        return

    next_version_number = (
        order.versions.aggregate(Max("version_number"))["version_number__max"] or 0
    ) + 1
    version_status = (
        OrderVersion.Status.NEEDS_CLARIFICATION if context.ambiguities else OrderVersion.Status.VALIDATED
    )
    missing_fields, evidence = _intake_extras(order)

    snapshot = {
        "items": [item.model_dump(mode="json") for item in context.items],
        "hints": [hint.model_dump(mode="json") for hint in context.hints],
        "resolvedItems": [r.model_dump(mode="json") for r in context.resolvedItems],
        "ambiguities": [a.model_dump(mode="json") for a in context.ambiguities],
        "evidence": evidence,
    }
    first_question = (
        context.ambiguities[0].ambiguities[0].question if context.ambiguities else ""
    )

    version = OrderVersion.objects.create(
        order=order,
        version_number=next_version_number,
        status=version_status,
        delivery_date=context.deliveryDate,
        missing_fields=missing_fields,
        clarification_question=first_question,
        total=Decimal(str(context.total)) if context.total is not None else None,
        created_by_agent="validation",
        context_snapshot=snapshot,
    )
    order.current_version = version
    order.save(update_fields=["state", "current_version", "updated_at"])

    _sync_order_items(version, context)


def _sync_order_items(version: OrderVersion, context: OrderContext) -> None:
    """Materializa `resolvedItems`/`ambiguities` como linhas de `OrderItem`
    — leitura relacional cômoda (admin, futuras queries), não a fonte da
    verdade (essa é `context_snapshot`, reconstruída em `build_context`)."""

    drafts_by_id = {item.id: item for item in context.items}

    for resolved in context.resolvedItems:
        draft = drafts_by_id.get(resolved.itemRef)
        quantity = Decimal(str(draft.quantity)) if draft else Decimal("0")
        unit_price = Decimal(str(resolved.unitPrice))
        OrderItem.objects.create(
            order_version=version,
            raw_text=draft.rawText if draft else "",
            product_hint=draft.productGuess if draft else "",
            sku=resolved.sku,
            unit=resolved.unit,
            quantity=quantity,
            unit_price=unit_price,
            subtotal=quantity * unit_price,
            in_stock=resolved.inStock,
        )

    for ambiguous in context.ambiguities:
        draft = drafts_by_id.get(ambiguous.itemRef)
        OrderItem.objects.create(
            order_version=version,
            raw_text=draft.rawText if draft else "",
            product_hint=draft.productGuess if draft else "",
            unit=draft.unit if draft else "",
            quantity=Decimal(str(draft.quantity)) if draft else Decimal("0"),
        )


@transaction.atomic
def _ingest(
    *,
    customer_id: int,
    message_text: str,
    channel: str = Message.Channel.TEXT,
    audio_file=None,
    transcription: str = "",
    transcription_confidence: float | None = None,
    source: str = Conversation.Source.SIMULATED,
) -> PipelineOutcome:
    """Núcleo comum de `ingest_message` (texto) e `ingest_audio_message`
    (voz, E9): cria conversa+pedido e dispara o pipeline completo
    (Intake → Memory → Validation) via Supervisor. Voz e texto convergem
    aqui de propósito (RF44/CLAUDE.md: "áudio é apenas mais um canal de
    entrada, não um fluxo paralelo") — a única diferença entre os dois
    caminhos é o que vai no `Message` (canal, áudio, transcrição); o
    pipeline em si nunca sabe de onde `message_text` veio.

    `source` (E10) segue a mesma lógica um nível acima: marca em qual
    canal a conversa nasceu (chat simulado ou WhatsApp real) só para a
    resposta voltar pelo canal certo — o Supervisor e os agentes não
    olham esse campo."""

    customer = Customer.objects.get(pk=customer_id)
    conversation = Conversation.objects.create(customer=customer, source=source)
    order = Order.objects.create(customer=customer, conversation=conversation)
    Message.objects.create(
        conversation=conversation,
        order=order,
        sender=Message.Sender.CUSTOMER,
        content=message_text,
        channel=channel,
        audio_file=audio_file,
        transcription=transcription,
        transcription_confidence=transcription_confidence,
    )

    context = build_context(order)
    result = _run_step(_supervisor().receive_message, AgentName.ORDER_INTAKE, context, message_text)
    _persist_context(order, context, result)
    reply_to_customer(order, result)
    return PipelineOutcome(order=order, result=result)


def ingest_message(
    *, customer_id: int, message: str, source: str = Conversation.Source.SIMULATED
) -> PipelineOutcome:
    """POST /api/orders/ingest — mensagem de texto."""

    return _ingest(customer_id=customer_id, message_text=message, source=source)


def ingest_audio_message(
    *,
    customer_id: int,
    audio_file,
    transcription_text: str,
    transcription_confidence: float | None = None,
) -> PipelineOutcome:
    """POST /api/orders/ingest-audio (E9) — o áudio já foi transcrito por
    `apps.core.voice.transcribe` antes de chegar aqui; esta função só
    decide que a transcrição alimenta o mesmo `_ingest` do texto (RF44) e
    que o áudio original + a transcrição ficam presos ao `Message` como
    evidência (RF45, complementando RF05)."""

    return _ingest(
        customer_id=customer_id,
        message_text=transcription_text,
        channel=Message.Channel.VOICE,
        audio_file=audio_file,
        transcription=transcription_text,
        transcription_confidence=transcription_confidence,
    )


@transaction.atomic
def submit_customer_reply(*, order_id: int, message: str, item_ref: str | None = None) -> PipelineOutcome:
    """POST /api/orders/{id}/customer-reply — resposta do cliente a uma
    pergunta de esclarecimento. `item_ref` é opcional na API (o cliente
    não sabe o id interno do item): sem ele, assume o primeiro item ainda
    ambíguo — cobre o caso comum de uma única pendência por vez."""

    order = Order.objects.select_related("customer", "conversation", "current_version").get(pk=order_id)
    context = build_context(order)

    if item_ref is None:
        if not context.ambiguities:
            raise OrderServiceError("não há esclarecimento pendente para este pedido")
        item_ref = context.ambiguities[0].itemRef

    Message.objects.create(
        conversation=order.conversation,
        order=order,
        sender=Message.Sender.CUSTOMER,
        content=message,
    )

    try:
        result = _run_step(_supervisor().customer_reply, AgentName.VALIDATION, context, item_ref, message)
    except OrchestratorError as exc:
        raise OrderServiceError(str(exc)) from exc

    _persist_context(order, context, result)
    reply_to_customer(order, result)
    return PipelineOutcome(order=order, result=result)


@transaction.atomic
def confirm_customer(*, order_id: int) -> Order:
    """POST /api/orders/{id}/confirm — confirmação do cliente, vinculada
    à versão exata (`order.current_version`). Não chama agente (guardrail
    do Supervisor: confirmação de resumo não precisa de LLM nem de tool)."""

    order = Order.objects.select_related("current_version").get(pk=order_id)
    context = build_context(order)

    try:
        _supervisor().customer_confirm(context)
    except OrchestratorError as exc:
        raise OrderServiceError(str(exc)) from exc

    CustomerConfirmation.objects.get_or_create(order_version=order.current_version)
    order.state = context.state.value
    order.save(update_fields=["state", "updated_at"])
    reply_to_customer(order)
    return order


@transaction.atomic
def approve_operator(*, order_id: int, approved_by: str, notes: str = "") -> PipelineOutcome:
    """POST /api/orders/{id}/approve — aprovação humana; só então o
    Supervisor libera a escrita no ERP (guardrail #3 do CLAUDE.md)."""

    order = Order.objects.select_related("current_version").get(pk=order_id)
    context = build_context(order)

    if not context.approvals.customerConfirmed:
        raise OrderServiceError("pedido ainda não foi confirmado pelo cliente")

    OperatorApproval.objects.get_or_create(
        order_version=order.current_version,
        defaults={"approved_by": approved_by, "notes": notes},
    )

    try:
        result = _run_step(_supervisor().operator_approve, AgentName.ERP_EXECUTION, context)
    except OrchestratorError as exc:
        raise OrderServiceError(str(exc)) from exc

    order.state = context.state.value
    if result.status == AgentStatus.OK and context.erpReceipt is not None:
        version = order.current_version
        snapshot = dict(version.context_snapshot or {})
        snapshot["erpReceipt"] = context.erpReceipt.model_dump(mode="json")
        version.context_snapshot = snapshot
        version.save(update_fields=["context_snapshot"])
    order.save(update_fields=["state", "updated_at"])
    reply_to_customer(order, result)
    return PipelineOutcome(order=order, result=result)


def reset_demo() -> None:
    """POST /api/demo/reset — restaura o dataset congelado a um estado
    idêntico (RF40, RNF03: "a demo roda 3x seguidas").

    `seed.py` (o comando de seed) só faz `.objects.all().delete()` antes
    de repopular — isso apaga as linhas, mas o Postgres não reinicia as
    sequences de PK sozinho numa exclusão comum (só em TRUNCATE ...
    RESTART IDENTITY). Sem isso, cada reset desloca todos os ids pra
    cima, e "estado idêntico" vira "mesmos dados, ids diferentes" — o
    suficiente pra quebrar qualquer id fixo (num teste do Postman, no
    frontend). `flush` é o comando padrão do Django pra isso: dá TRUNCATE
    com RESTART IDENTITY CASCADE em todas as tabelas antes do seed rodar
    de novo.
    """

    call_command("flush", interactive=False)
    call_command("seed")


def response_text_for_order(order: Order) -> str:
    """Texto da "resposta atual" do pedido — pergunta de esclarecimento
    pendente, ou resumo com itens e total (RF48). Usado por
    `GET /api/orders/{id}/voice-reply` (E9) como o texto que
    `apps.core.voice.synthesize` transforma em áudio; também é o texto
    devolvido quando a síntese falha (RF49: o texto sempre existe, o
    áudio é que é opcional).

    Função pura e determinística — só formata dados que já passaram pelo
    Validation Agent (`context.resolvedItems`/`total`, nunca calculados
    aqui), o mesmo espírito do guardrail #2 do CLAUDE.md aplicado à
    apresentação, não só ao cálculo."""

    version = order.current_version
    if version is None:
        return "Ainda estou processando o seu pedido, um momento."

    context = build_context(order)

    if context.ambiguities:
        return context.ambiguities[0].ambiguities[0].question

    if context.resolvedItems and context.total is not None:
        drafts_by_id = {item.id: item for item in context.items}
        lines = ["Aqui está o resumo do seu pedido."]
        for resolved in context.resolvedItems:
            draft = drafts_by_id.get(resolved.itemRef)
            product = draft.productGuess if draft else resolved.sku
            quantity = draft.quantity if draft else None
            quantity_text = f"{quantity:g}" if quantity is not None else "?"
            lines.append(
                f"{quantity_text} {resolved.unit} de {product}, a R$ {resolved.unitPrice:.2f} cada."
            )
        lines.append(f"Total: R$ {context.total:.2f}.")
        if order.state == OrderState.READY_FOR_CONFIRMATION.value:
            lines.append("Posso confirmar o pedido?")
        return " ".join(lines)

    return "Ainda não há um resumo disponível para este pedido."


# ---------------------------------------------------------------------------
# Canal de saída (E10) — responder ao cliente pela conversa de origem
# ---------------------------------------------------------------------------
#
# RF19 ("enviar ao cliente apenas a pergunta necessária, pela mesma
# conversa") e RF31 ("após sucesso, o cliente deve receber uma confirmação
# final") sempre existiram como texto; o que faltava era o transporte. Aqui
# a resposta vira uma `Message` de sistema na mesma conversa — o registro
# que o console simulado lê — e, SÓ se a conversa nasceu no WhatsApp real,
# também sai pelo gateway (`whatsapp.py`). Conversa simulada não chama
# nada externo: ela é o fallback obrigatório da demo e continua funcionando
# com o gateway desligado.


def customer_reply_text(order: Order, result: AgentResult | None = None) -> str:
    """O que dizer ao cliente no estado atual do pedido. Devolve string
    vazia quando não há nada a dizer (estado intermediário sem pendência).

    Determinística e sem dado comercial novo: o texto de esclarecimento e
    o resumo vêm de `response_text_for_order` (que só formata o que o
    Validation Agent produziu) e o número do pedido vem do recibo do ERP
    (guardrail #1: nada é inventado aqui)."""

    if result is not None and result.status != AgentStatus.OK:
        # Guardrail #7: a falha não vira silêncio nem falso sucesso. O
        # cliente é avisado de que travou; o motivo real fica na timeline
        # e nos logs, para o operador — não para o WhatsApp do cliente.
        return (
            "Tive um problema técnico ao processar sua mensagem agora. "
            "O time já foi avisado e vai te retornar."
        )

    state = order.state

    if state in (OrderState.WAITING_CUSTOMER.value, OrderState.READY_FOR_CONFIRMATION.value):
        return response_text_for_order(order)

    if state in (OrderState.CUSTOMER_CONFIRMED.value, OrderState.PENDING_APPROVAL.value):
        return (
            "Confirmação recebida! Seu pedido está em aprovação final "
            "e eu te aviso assim que ele for registrado."
        )

    if state == OrderState.SENT_TO_ERP.value:
        # RF31 — confirmação final, com o número que o ERP devolveu.
        context = build_context(order)
        receipt = context.erpReceipt
        if receipt is None:
            return "Pedido registrado com sucesso!"
        total_text = f" Total: R$ {context.total:.2f}." if context.total is not None else ""
        return f"Pedido registrado com sucesso! Número no ERP: {receipt.externalOrderId}.{total_text}"

    if state == OrderState.ERP_EXECUTION_FAILED.value:
        return (
            "Tivemos um problema ao registrar seu pedido no sistema. "
            "O time já foi avisado e vai te retornar."
        )

    return ""


def send_to_customer(order: Order, text: str) -> Message | None:
    """Grava a resposta como `Message` de sistema na conversa do pedido e
    agenda a entrega pelo canal real, se for o caso. Nunca levanta por
    falha de transporte — `whatsapp.deliver` registra `failed` na própria
    mensagem e segue (o gateway é enhancement; o pedido não depende
    dele)."""

    if not text.strip():
        return None

    conversation = order.conversation
    is_real_channel = conversation.source == Conversation.Source.WHATSAPP_WEB
    message = Message.objects.create(
        conversation=conversation,
        order=order,
        sender=Message.Sender.SYSTEM,
        content=text,
        delivery_status=(
            Message.DeliveryStatus.PENDING
            if is_real_channel
            else Message.DeliveryStatus.NOT_APPLICABLE
        ),
    )
    whatsapp.deliver_on_commit(message)
    return message


def reply_to_customer(order: Order, result: AgentResult | None = None) -> Message | None:
    """Resposta automática ao cliente depois de um passo do pipeline."""

    return send_to_customer(order, customer_reply_text(order, result))


# ---------------------------------------------------------------------------
# Canal de entrada (E10) — mensagem vinda do WhatsApp real
# ---------------------------------------------------------------------------
#
# O gateway Node não conhece pedido nem estado: ele só entrega "este
# telefone disse este texto". Quem decide se isso é um pedido novo, uma
# resposta de esclarecimento ou uma confirmação é este roteador — e ele
# só chama as MESMAS funções que o console simulado chama
# (`ingest_message`, `submit_customer_reply`, `confirm_customer`). Não
# existe pipeline paralelo pro WhatsApp real, como não existe pra voz.

# Estados em que uma mensagem do cliente continua um pedido existente em
# vez de abrir outro. Fora daqui (em aprovação, já no ERP, ou travado numa
# falha) o pedido não espera mais nada do cliente, então a próxima
# mensagem dele começa um pedido novo.
_OPEN_FOR_CUSTOMER_STATES = (
    OrderState.WAITING_CUSTOMER.value,
    OrderState.READY_FOR_CONFIRMATION.value,
)

# Confirmação é reconhecida por lista fechada, sem LLM: é decisão de
# fluxo, não interpretação de pedido. Qualquer coisa fora da lista NÃO
# vira confirmação (guardrail #6: ambiguidade nunca é resolvida em
# silêncio) — o cliente recebe o resumo de novo e a pergunta explícita.
_CONFIRMATION_WORDS = frozenset(
    {
        "sim",
        "s",
        "ok",
        "okay",
        "confirmo",
        "confirmado",
        "confirma",
        "confirmar",
        "pode confirmar",
        "pode fechar",
        "pode mandar",
        "pode seguir",
        "isso",
        "isso mesmo",
        "positivo",
        "fechado",
        "fechou",
        "beleza",
        "blz",
        "perfeito",
        "certo",
        "esta certo",
        "ta certo",
        "aprovado",
        "sim confirmo",
        "sim pode confirmar",
        "👍",
        "👍🏻",
        "👍🏼",
        "👍🏽",
        "👍🏾",
        "👍🏿",
    }
)


class UnknownCustomerError(OrderServiceError):
    """O telefone que mandou a mensagem não corresponde a exatamente um
    cliente cadastrado. Não existe "criar cliente na hora": cliente é dado
    comercial e vem do cadastro, nunca do canal (guardrail #1)."""


@dataclass
class InboundOutcome:
    """Resultado do roteamento de uma mensagem do WhatsApp real.
    `action` diz qual caminho existente foi usado — é o que o gateway (e o
    operador, no log) precisa pra entender o que aconteceu."""

    order: Order
    action: str  # created | clarification_reply | confirmed | confirmation_pending
    result: AgentResult | None = None


def _normalize_text(text: str) -> str:
    """minúsculas, sem acento e sem pontuação — só pra comparar intenção
    de confirmação, nunca pra interpretar o conteúdo do pedido."""

    stripped = unicodedata.normalize("NFKD", text or "").casefold()
    stripped = "".join(c for c in stripped if not unicodedata.combining(c))
    cleaned = "".join(c if (c.isalnum() or c.isspace()) else " " for c in stripped)
    return " ".join(cleaned.split())


def is_confirmation(text: str) -> bool:
    """Só reconhece confirmação inequívoca (lista fechada ou uma frase
    curta começando em "confirm..."). Na dúvida, devolve False — quem
    chama repete a pergunta em vez de confirmar por conta própria."""

    if (text or "").strip() in _CONFIRMATION_WORDS:  # emoji não sobrevive à normalização
        return True

    normalized = _normalize_text(text)
    if not normalized:
        return False
    if normalized in _CONFIRMATION_WORDS:
        return True

    words = normalized.split()
    return len(words) <= 3 and words[0].startswith("confirm")


def find_customer_by_phone(phone: str) -> Customer:
    """Telefone -> cliente cadastrado. Compara só dígitos e casa também
    pelos 8 últimos, porque o mesmo número aparece em formatos diferentes
    (`+55 (11) 99999-0001`, `5511999990001@c.us`, com ou sem o 9). Mais de
    um cliente batendo é ambiguidade: levanta em vez de escolher um
    (guardrail #6).

    Varre os clientes em Python de propósito — o dataset da demo tem
    poucas linhas e o formato do telefone no cadastro é livre, então
    normalizar dos dois lados é mais confiável que um LIKE no banco."""

    digits = whatsapp.normalize_phone(phone)
    if len(digits) < 8:
        raise UnknownCustomerError(f"telefone inválido ou incompleto: '{phone}'")

    matches = [
        customer
        for customer in Customer.objects.exclude(phone="")
        if _phone_matches(digits, whatsapp.normalize_phone(customer.phone))
    ]

    if not matches:
        raise UnknownCustomerError(f"nenhum cliente cadastrado com o telefone {digits}")
    if len(matches) > 1:
        names = ", ".join(c.name for c in matches)
        raise UnknownCustomerError(f"telefone {digits} bate com mais de um cliente ({names})")
    return matches[0]


def _phone_matches(incoming: str, stored: str) -> bool:
    if len(stored) < 8:
        return False
    return incoming == stored or incoming[-8:] == stored[-8:]


def _open_whatsapp_order(customer: Customer) -> Order | None:
    """Último pedido do cliente que ainda espera resposta dele E nasceu no
    WhatsApp real. O filtro por `source` é proposital: mensagem do
    WhatsApp nunca entra num pedido aberto no chat simulado (e vice-versa)
    — os dois canais ficam isolados, que é o que garante a demo simulada
    rodando com o gateway ligado ou desligado."""

    return (
        Order.objects.filter(
            customer=customer,
            state__in=_OPEN_FOR_CUSTOMER_STATES,
            conversation__source=Conversation.Source.WHATSAPP_WEB,
        )
        .select_related("customer", "conversation", "current_version")
        .order_by("-created_at")
        .first()
    )


def handle_inbound_whatsapp(*, phone: str, text: str) -> InboundOutcome:
    """POST /api/whatsapp/inbound — mensagem recebida de um celular real.

    Roteia para o caminho que já existe, conforme o estado do pedido
    aberto do cliente:

    - sem pedido aberto        -> `ingest_message` (pedido novo)
    - `waiting_customer`       -> `submit_customer_reply` (esclarecimento)
    - `ready_for_confirmation` -> `confirm_customer` se a mensagem for uma
      confirmação inequívoca; senão repete o resumo e a pergunta.
    """

    message = (text or "").strip()
    if not message:
        raise OrderServiceError("mensagem vazia")

    customer = find_customer_by_phone(phone)
    order = _open_whatsapp_order(customer)

    if order is None:
        outcome = ingest_message(
            customer_id=customer.id,
            message=message,
            source=Conversation.Source.WHATSAPP_WEB,
        )
        return InboundOutcome(order=outcome.order, action="created", result=outcome.result)

    if order.state == OrderState.WAITING_CUSTOMER.value:
        outcome = submit_customer_reply(order_id=order.id, message=message)
        return InboundOutcome(
            order=outcome.order, action="clarification_reply", result=outcome.result
        )

    # Em `ready_for_confirmation` nenhum dos dois caminhos abaixo grava a
    # mensagem do cliente (confirm_customer não recebe texto), mas ela é
    # evidência da confirmação — fica registrada na conversa de qualquer
    # forma, tenha confirmado ou não.
    Message.objects.create(
        conversation=order.conversation,
        order=order,
        sender=Message.Sender.CUSTOMER,
        content=message,
    )

    if is_confirmation(message):
        confirmed = confirm_customer(order_id=order.id)
        return InboundOutcome(order=confirmed, action="confirmed")

    # Não confirmou de forma clara: nada avança e o cliente recebe o
    # resumo outra vez, com a pergunta explícita.
    send_to_customer(
        order,
        f"{response_text_for_order(order)} Responda CONFIRMO para eu registrar o pedido.",
    )
    return InboundOutcome(order=order, action="confirmation_pending")
