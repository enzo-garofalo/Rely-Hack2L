"""Serialização da Order API (E7). Não usa `rest_framework.Serializer`
clássico de propósito: a resposta mistura campos do `Order`/`OrderVersion`
(Django) com o `OrderContext` reconstruído (Pydantic, via
`order_service.build_context`) — montar o dict diretamente é mais direto
que forçar as duas fontes num único `ModelSerializer`.
"""

from __future__ import annotations

from apps.agents.schemas import AmbiguousItem, OrderItemDraft, ResolvedItem

from .models import CustomerConfirmation, OperatorApproval, Order
from .order_service import build_context


def _serialize_customer(customer) -> dict:
    return {"id": customer.id, "name": customer.name, "phone": customer.phone}


def _serialize_resolved(draft: OrderItemDraft | None, resolved: ResolvedItem) -> dict:
    quantity = draft.quantity if draft else None
    return {
        "itemRef": resolved.itemRef,
        "rawText": draft.rawText if draft else "",
        "productGuess": draft.productGuess if draft else "",
        "quantity": quantity,
        "unit": draft.unit if draft else "",
        "status": "resolved",
        "sku": resolved.sku,
        "catalogUnit": resolved.unit,
        "unitPrice": resolved.unitPrice,
        "subtotal": (quantity * resolved.unitPrice) if quantity is not None else None,
        "inStock": resolved.inStock,
    }


def _serialize_ambiguous(draft: OrderItemDraft | None, ambiguous: AmbiguousItem) -> dict:
    return {
        "itemRef": ambiguous.itemRef,
        "rawText": draft.rawText if draft else "",
        "productGuess": draft.productGuess if draft else "",
        "quantity": draft.quantity if draft else None,
        "unit": draft.unit if draft else "",
        "status": "ambiguous",
        "ambiguities": [
            {"field": a.field, "question": a.question, "candidates": a.candidates}
            for a in ambiguous.ambiguities
        ],
    }


def serialize_order(order: Order) -> dict:
    """GET /api/orders/{id} — estado completo do pedido: itens, evidência,
    validações, esclarecimento pendente e resumo (E7)."""

    context = build_context(order)
    version = order.current_version
    drafts_by_id = {item.id: item for item in context.items}

    items = [_serialize_resolved(drafts_by_id.get(r.itemRef), r) for r in context.resolvedItems]
    items += [_serialize_ambiguous(drafts_by_id.get(a.itemRef), a) for a in context.ambiguities]

    pending_clarification = None
    if context.ambiguities:
        first_item = context.ambiguities[0]
        first_ambiguity = first_item.ambiguities[0]
        pending_clarification = {
            "itemRef": first_item.itemRef,
            "field": first_ambiguity.field,
            "question": first_ambiguity.question,
            "candidates": first_ambiguity.candidates,
        }

    snapshot = version.context_snapshot if version else {}
    current_version = None
    if version is not None:
        current_version = {
            "versionNumber": version.version_number,
            "status": version.status,
            "deliveryDate": version.delivery_date.isoformat() if version.delivery_date else None,
            "missingFields": version.missing_fields,
            "evidence": snapshot.get("evidence", []),
            "total": context.total,
            "items": items,
            "pendingClarification": pending_clarification,
            "customerConfirmed": context.approvals.customerConfirmed,
            "operatorApproved": context.approvals.operatorApproved,
            "erpReceipt": context.erpReceipt.model_dump(mode="json") if context.erpReceipt else None,
        }

    return {
        "id": order.id,
        "state": order.state,
        "conversationId": order.conversation_id,
        "customer": _serialize_customer(order.customer),
        "createdAt": order.created_at.isoformat(),
        "updatedAt": order.updated_at.isoformat(),
        "currentVersion": current_version,
    }


def serialize_timeline(order: Order) -> dict:
    """GET /api/orders/{id}/timeline — AgentRun + ToolCall + confirmações
    consolidados em ordem cronológica (RF37-39)."""

    events: list[dict] = []

    for message in order.messages.all():
        event = {
            "type": "message",
            "at": message.created_at.isoformat(),
            "sender": message.sender,
            "channel": message.channel,
            "content": message.content,
        }
        if message.channel == message.Channel.VOICE:
            # RF45/RF46: o áudio original fica recuperável (não só
            # guardado), e a confiança da transcrição fica visível pro
            # operador auditar — `content` já é a transcrição em si.
            event["transcription"] = message.transcription
            event["transcriptionConfidence"] = message.transcription_confidence
            event["audioUrl"] = message.audio_file.url if message.audio_file else None
        events.append(event)

    agent_runs = order.agent_runs.prefetch_related("tool_calls").all()
    for run in agent_runs:
        finished_at = (run.finished_at or run.started_at).isoformat()
        events.append(
            {
                "type": "agent_run",
                "at": run.started_at.isoformat(),
                "agent": run.agent_name,
                "previousState": run.previous_state,
                "nextState": run.next_state,
                "success": run.success,
                "reason": run.reason,
                "toolCalls": [
                    {
                        "tool": tool_call.tool_name,
                        "input": tool_call.input_data,
                        "output": tool_call.output_data,
                        "success": tool_call.success,
                        "error": tool_call.error_message,
                        "at": tool_call.created_at.isoformat(),
                    }
                    for tool_call in run.tool_calls.all()
                ],
            }
        )
        # Entrada dedicada de transição (RF37/E8: "AgentRun + ToolCall +
        # transições ordenados"), além do agent_run acima que já carrega
        # previousState/nextState — útil pra uma UI renderizar só a
        # sequência de estados sem precisar entender a forma de agent_run.
        # Sem transição de fato (falha antes de qualquer mudança, ou
        # next_state nunca setado) não gera entrada — nada é inventado.
        if run.next_state and run.previous_state != run.next_state:
            events.append(
                {
                    "type": "state_transition",
                    "at": finished_at,
                    "from": run.previous_state,
                    "to": run.next_state,
                    "causedBy": run.agent_name,
                }
            )

    for confirmation in CustomerConfirmation.objects.filter(order_version__order=order):
        at = confirmation.confirmed_at.isoformat()
        events.append(
            {
                "type": "customer_confirmation",
                "at": at,
                "versionNumber": confirmation.order_version.version_number,
            }
        )
        # customer_confirm() no orchestrator.py anda direto
        # ready_for_confirmation -> customer_confirmed -> pending_approval,
        # sem chamar agente — por isso as duas transições são sintéticas
        # aqui, e não vêm de um AgentRun.
        events.append(
            {
                "type": "state_transition",
                "at": at,
                "from": "ready_for_confirmation",
                "to": "customer_confirmed",
                "causedBy": "customer_confirm",
            }
        )
        events.append(
            {
                "type": "state_transition",
                "at": at,
                "from": "customer_confirmed",
                "to": "pending_approval",
                "causedBy": "customer_confirm",
            }
        )

    for approval in OperatorApproval.objects.filter(order_version__order=order):
        at = approval.approved_at.isoformat()
        events.append(
            {
                "type": "operator_approval",
                "at": at,
                "versionNumber": approval.order_version.version_number,
                "approvedBy": approval.approved_by,
                "notes": approval.notes,
            }
        )
        # pending_approval -> sending_to_erp acontece antes do Supervisor
        # chamar o ERP Execution Agent; a transição seguinte
        # (sending_to_erp -> sent_to_erp/erp_execution_failed) já vem do
        # agent_run do erp_execution, então não é duplicada aqui.
        events.append(
            {
                "type": "state_transition",
                "at": at,
                "from": "pending_approval",
                "to": "sending_to_erp",
                "causedBy": "operator_approve",
            }
        )

    events.sort(key=lambda e: e["at"])
    return {"orderId": order.id, "events": events}
