from django.core.management import call_command
from django.test import TestCase

from apps.agents import memory
from apps.agents.context import CustomerRef, OrderContext, OrderState
from apps.agents.schemas import AgentStatus, OrderItemDraft
from apps.core.models import AgentRun, Conversation, Customer, MemoryEntry, Order, ToolCall


class DeterministicMemoryTests(TestCase):
    def setUp(self):
        call_command("seed_demo", verbosity=0)
        self.customer = Customer.objects.get()
        conversation = Conversation.objects.create(customer=self.customer)
        self.order = Order.objects.create(customer=self.customer, conversation=conversation)

    def test_recalls_only_approved_aliases_without_llm(self):
        context = OrderContext(
            orderId=self.order.id,
            conversationId=str(self.order.conversation_id),
            customer=CustomerRef(id=self.customer.id, phone=self.customer.phone),
            state=OrderState.MEMORY_LOADED,
            items=[
                OrderItemDraft(
                    id="coca",
                    rawText="10 caixas de coca 2L",
                    productGuess="Coca-Cola 2L",
                    quantity=10,
                    unit="caixas",
                    confidence=0.9,
                ),
                OrderItemDraft(
                    id="oleo",
                    rawText="15 caixas do óleo da última vez",
                    productGuess="Óleo de cozinha",
                    quantity=15,
                    unit="caixas",
                    confidence=0.5,
                ),
            ],
        )

        result = memory.run(context)

        self.assertEqual(result.status, AgentStatus.OK)
        self.assertEqual(
            {hint.itemRef: hint.suggests.value for hint in result.data.hints},
            {"coca": "COCA-2L-CX6", "oleo": "OLEO-SOJA-900ML-CX20"},
        )
        self.assertEqual(result.data.preferences[0].value, "morning")
        self.assertEqual(AgentRun.objects.filter(order=self.order, agent_name="memory").count(), 1)
        self.assertEqual(ToolCall.objects.filter(agent_run__order=self.order, tool_name="get_customer_memory").count(), 1)

    def test_does_not_match_alias_inside_another_word(self):
        MemoryEntry.objects.create(
            customer=self.customer,
            kind=MemoryEntry.Kind.PRODUCT_ALIAS,
            product_hint="sal",
            sku="COCA-2L-CX6",
        )
        context = OrderContext(
            orderId=self.order.id,
            conversationId=str(self.order.conversation_id),
            customer=CustomerRef(id=self.customer.id, phone=self.customer.phone),
            state=OrderState.MEMORY_LOADED,
            items=[
                OrderItemDraft(
                    id="salgado",
                    rawText="10 caixas de salgados",
                    productGuess="salgados",
                    quantity=10,
                    unit="caixas",
                    confidence=0.9,
                )
            ],
        )

        result = memory.run(context)

        self.assertEqual(result.data.hints, [])
