from django.core.management import call_command
from django.test import TestCase
from pydantic import ValidationError

from apps.agents import tools
from apps.agents.schemas import OrderItemDraft
from apps.core.models import AgentRun, Conversation, Customer, Order


class AgentContractTests(TestCase):
    def test_item_confidence_is_required_and_bounded(self):
        valid = OrderItemDraft(
            id="item-1",
            rawText="uma caixa",
            productGuess="coca",
            quantity=1,
            unit="caixa",
            confidence=0.9,
        )
        self.assertEqual(valid.confidence, 0.9)

        with self.assertRaises(ValidationError):
            OrderItemDraft(
                id="item-1",
                rawText="uma caixa",
                productGuess="coca",
                quantity=1,
                unit="caixa",
                confidence=1.1,
            )


class CatalogSearchTests(TestCase):
    def setUp(self):
        call_command("seed_demo", verbosity=0)
        customer = Customer.objects.get()
        conversation = Conversation.objects.create(customer=customer)
        order = Order.objects.create(customer=customer, conversation=conversation)
        self.agent_run = AgentRun.objects.create(
            order=order,
            agent_name=AgentRun.Agent.VALIDATION,
            previous_state="validating",
        )

    def test_matches_catalog_across_name_and_alias_ignoring_llm_qualifier(self):
        matches = tools.search_catalog("Coca-Cola Zero (provável)", agent_run=self.agent_run)

        self.assertEqual([match.sku for match in matches], ["COCA-ZERO-LATA-CX12"])
