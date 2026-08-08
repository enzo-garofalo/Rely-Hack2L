from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.agents.schemas import AgentStatus

from . import order_service
from .models import Customer, Order
from .serializers import serialize_order, serialize_timeline


@api_view(["GET"])
def health(request):
    return Response({"status": "ok"})


def _pipeline_response(outcome: order_service.PipelineOutcome, *, ok_status: int) -> Response:
    """Monta a resposta comum às ações que passam pelo Supervisor:
    sucesso vira `ok_status`, `AgentStatus.ERROR` vira 502 com o motivo
    exposto em `agentError` — nunca escondido (guardrail #7 do CLAUDE.md)."""

    payload = {"orderId": outcome.order.id, "state": outcome.order.state}
    if outcome.result.status != AgentStatus.OK:
        payload["agentError"] = outcome.result.error
        return Response(payload, status=status.HTTP_502_BAD_GATEWAY)
    return Response(payload, status=ok_status)


class OrderIngestView(APIView):
    """POST /api/orders/ingest — recebe a mensagem, cria conversa+pedido,
    dispara o pipeline (E7)."""

    def post(self, request):
        customer_id = request.data.get("customerId")
        message = (request.data.get("message") or "").strip()
        if not customer_id or not message:
            return Response(
                {"detail": "customerId e message são obrigatórios."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            outcome = order_service.ingest_message(customer_id=customer_id, message=message)
        except Customer.DoesNotExist:
            return Response({"detail": "customer não encontrado."}, status=status.HTTP_404_NOT_FOUND)

        return _pipeline_response(outcome, ok_status=status.HTTP_201_CREATED)


class OrderDetailView(APIView):
    """GET /api/orders/{id} — estado completo do pedido (E7)."""

    def get(self, request, pk):
        order = get_object_or_404(
            Order.objects.select_related("customer", "current_version"), pk=pk
        )
        return Response(serialize_order(order))


class OrderCustomerReplyView(APIView):
    """POST /api/orders/{id}/customer-reply — resposta do cliente a um
    esclarecimento pendente (E7)."""

    def post(self, request, pk):
        get_object_or_404(Order, pk=pk)
        message = (request.data.get("message") or "").strip()
        item_ref = request.data.get("itemRef")
        if not message:
            return Response({"detail": "message é obrigatório."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            outcome = order_service.submit_customer_reply(order_id=pk, message=message, item_ref=item_ref)
        except order_service.OrderServiceError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)

        return _pipeline_response(outcome, ok_status=status.HTTP_200_OK)


class OrderConfirmView(APIView):
    """POST /api/orders/{id}/confirm — confirmação do cliente na versão
    atual (E7)."""

    def post(self, request, pk):
        get_object_or_404(Order, pk=pk)
        try:
            order = order_service.confirm_customer(order_id=pk)
        except order_service.OrderServiceError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)

        return Response({"orderId": order.id, "state": order.state}, status=status.HTTP_200_OK)


class OrderApproveView(APIView):
    """POST /api/orders/{id}/approve — aprovação do operador; dispara a
    execução no ERP (E7)."""

    def post(self, request, pk):
        get_object_or_404(Order, pk=pk)
        approved_by = (request.data.get("approvedBy") or "").strip()
        notes = request.data.get("notes") or ""
        if not approved_by:
            return Response({"detail": "approvedBy é obrigatório."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            outcome = order_service.approve_operator(order_id=pk, approved_by=approved_by, notes=notes)
        except order_service.OrderServiceError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)

        response = _pipeline_response(outcome, ok_status=status.HTTP_200_OK)
        if outcome.result.status == AgentStatus.OK:
            version = outcome.order.current_version
            response.data["erpReceipt"] = (version.context_snapshot or {}).get("erpReceipt") if version else None
        return response


class OrderTimelineView(APIView):
    """GET /api/orders/{id}/timeline — AgentRun + ToolCall + estados
    consolidados (E7, RF39)."""

    def get(self, request, pk):
        order = get_object_or_404(Order, pk=pk)
        return Response(serialize_timeline(order))


class DemoResetView(APIView):
    """POST /api/demo/reset — restaura o dataset congelado (RF40)."""

    def post(self, request):
        order_service.reset_demo()
        return Response({"status": "reset"})
