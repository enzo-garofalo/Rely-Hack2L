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
import re

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
            confidence=draft.confidence if draft else None,
        )

    for ambiguous in context.ambiguities:
        draft = drafts_by_id.get(ambiguous.itemRef)
        OrderItem.objects.create(
            order_version=version,
            raw_text=draft.rawText if draft else "",
            product_hint=draft.productGuess if draft else "",
            unit=draft.unit if draft else "",
            quantity=Decimal(str(draft.quantity)) if draft else Decimal("0"),
            confidence=draft.confidence if draft else None,
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
) -> PipelineOutcome:
    """Núcleo comum de `ingest_message` (texto) e `ingest_audio_message`
    (voz, E9): cria conversa+pedido e dispara o pipeline completo
    (Intake → Memory → Validation) via Supervisor. Voz e texto convergem
    aqui de propósito (RF44/CLAUDE.md: "áudio é apenas mais um canal de
    entrada, não um fluxo paralelo") — a única diferença entre os dois
    caminhos é o que vai no `Message` (canal, áudio, transcrição); o
    pipeline em si nunca sabe de onde `message_text` veio."""

    customer = Customer.objects.get(pk=customer_id)
    conversation = Conversation.objects.create(customer=customer)
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
    return PipelineOutcome(order=order, result=result)


def ingest_message(*, customer_id: int, message: str) -> PipelineOutcome:
    """POST /api/orders/ingest — mensagem de texto."""

    return _ingest(customer_id=customer_id, message_text=message)


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


def _observed_alias(raw_text: str) -> str:
    """Remove quantidade e singulariza a embalagem inicial para registrar
    o apelido confirmado, preservando o restante da fala como evidência.

    Ex.: ``6 fardos da zero`` vira ``fardo da zero``. Não tenta resolver
    produto nem SKU; isso já foi feito pelo Validation contra o catálogo.
    """

    without_quantity = re.sub(r"^\s*\d+(?:[.,]\d+)?\s+", "", raw_text).strip()
    return re.sub(
        r"^(caixas?|fardos?)\b",
        lambda match: "caixa" if match.group(1).startswith("caixa") else "fardo",
        without_quantity,
        count=1,
        flags=re.IGNORECASE,
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

    reply_message = Message.objects.create(
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

    # Uma proposta nasce somente quando uma pendência anterior foi
    # efetivamente resolvida contra o catálogo. Ela continua sendo apenas
    # pending_review: nunca vira MemoryEntry automaticamente.
    if result.status == AgentStatus.OK:
        draft = next((item for item in context.items if item.id == item_ref), None)
        resolved = next((item for item in context.resolvedItems if item.itemRef == item_ref), None)
        still_ambiguous = any(item.itemRef == item_ref for item in context.ambiguities)
        if draft is not None and resolved is not None and not still_ambiguous:
            memory.propose(
                context,
                observed=_observed_alias(draft.rawText),
                resolved_sku=resolved.sku,
                evidence_quote=message,
                conversation_ref=f"message-{reply_message.id}",
                source_order_version_id=order.current_version_id,
            )
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
    call_command("seed_demo")


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
