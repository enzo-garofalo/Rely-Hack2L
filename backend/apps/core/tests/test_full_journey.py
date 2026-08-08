from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from apps.agents.orchestrator import Agents
from apps.agents.schemas import (
    AgentName,
    AgentResult,
    AgentStatus,
    Ambiguity,
    AmbiguousItem,
    ErpReceipt,
    MemoryContext,
    OrderDraft,
    OrderItemDraft,
    ResolvedItem,
    ValidatedOrder,
)
from apps.erp_simulator.models import ErpOrder


class DeterministicJourneyTests(TestCase):
    def setUp(self):
        call_command("seed_demo", verbosity=0)
        self.client = APIClient()

    @staticmethod
    def agents():
        items = [
            OrderItemDraft(id="coca", rawText="10 caixas de coca 2L", productGuess="coca 2L", quantity=10, unit="caixa", confidence=0.98),
            OrderItemDraft(id="zero", rawText="6 fardos da zero", productGuess="zero", quantity=6, unit="fardo", confidence=0.62),
            OrderItemDraft(id="oleo", rawText="15 caixas do óleo da última vez", productGuess="óleo da última vez", quantity=15, unit="caixa", confidence=0.91),
        ]
        resolved_coca = ResolvedItem(itemRef="coca", sku="COCA-2L-CX6", unit="caixa com 6", unitPrice=54, inStock=True)
        resolved_zero = ResolvedItem(itemRef="zero", sku="COCA-ZERO-LATA-CX12", unit="fardo com 12", unitPrice=42, inStock=True)
        resolved_oleo = ResolvedItem(itemRef="oleo", sku="OLEO-SOJA-900ML-CX20", unit="caixa com 20", unitPrice=118, inStock=True)

        def intake(_context):
            return AgentResult(
                agent=AgentName.ORDER_INTAKE,
                status=AgentStatus.OK,
                data=OrderDraft(items=items, deliveryDate="2026-08-09", evidence=[item.rawText for item in items]),
            )

        def recall(_context):
            return AgentResult(agent=AgentName.OPERATIONAL_MEMORY, status=AgentStatus.OK, data=MemoryContext())

        def validate(_context, item_ref):
            if item_ref is None:
                data = ValidatedOrder(
                    items=[
                        resolved_coca,
                        resolved_oleo,
                        AmbiguousItem(
                            itemRef="zero",
                            ambiguities=[Ambiguity(
                                field="sku",
                                question="A Coca Zero é o fardo com 12 latas de 350 ml?",
                                candidates=["COCA-ZERO-LATA-CX12"],
                            )],
                        ),
                    ]
                )
            else:
                data = ValidatedOrder(items=[resolved_coca, resolved_oleo, resolved_zero], total=2562)
            return AgentResult(agent=AgentName.VALIDATION, status=AgentStatus.OK, data=data)

        def execute(context):
            data = ErpReceipt(
                externalOrderId="ERP-2026-TEST",
                idempotencyKey=f"order-{context.conversationId}-{context.orderId}",
                payload={
                    "customerId": context.customer.id,
                    "items": [{"sku": item.sku} for item in context.resolvedItems],
                    "total": context.total,
                },
            )
            return AgentResult(agent=AgentName.ERP_EXECUTION, status=AgentStatus.OK, data=data)

        return Agents(
            order_intake=intake,
            operational_memory=recall,
            validation=validate,
            erp_execution=execute,
        )

    def test_complete_http_journey_and_state_guards(self):
        with patch("apps.core.order_service._agents", return_value=self.agents()):
            ingest = self.client.post(
                "/api/orders/ingest/",
                {
                    "customerId": 1,
                    "message": "Quero 10 caixas de coca 2L, 6 fardos da zero e 15 caixas do óleo da última vez.",
                },
                format="json",
            )
            order_id = ingest.json()["orderId"]
            self.assertEqual(ingest.status_code, 201)
            self.assertEqual(ingest.json()["state"], "waiting_customer")

            reply = self.client.post(
                f"/api/orders/{order_id}/customer-reply/",
                {"message": "Sim, a lata de 350ml em fardo com 12.", "itemRef": "zero"},
                format="json",
            )
            self.assertEqual(reply.status_code, 200)
            self.assertEqual(reply.json()["state"], "ready_for_confirmation")

            confirm = self.client.post(f"/api/orders/{order_id}/confirm/", {}, format="json")
            repeated_confirm = self.client.post(f"/api/orders/{order_id}/confirm/", {}, format="json")
            self.assertEqual(confirm.json()["state"], "pending_approval")
            self.assertEqual(repeated_confirm.status_code, 409)

            approve = self.client.post(
                f"/api/orders/{order_id}/approve/",
                {"approvedBy": "Pedro", "notes": "Revisado"},
                format="json",
            )
            repeated_approve = self.client.post(
                f"/api/orders/{order_id}/approve/",
                {"approvedBy": "Pedro"},
                format="json",
            )

        self.assertEqual(approve.status_code, 200)
        self.assertEqual(approve.json()["state"], "sent_to_erp")
        self.assertEqual(approve.json()["erpReceipt"]["erpOrderId"], "ERP-2026-TEST")
        self.assertEqual(approve.json()["erpReceipt"]["payload"]["total"], 2562)
        self.assertEqual(repeated_approve.status_code, 409)
        # O stub não escreve no ERP: esta asserção garante que o teste não
        # mascara idempotência criando um efeito externo falso.
        self.assertEqual(ErpOrder.objects.count(), 0)
