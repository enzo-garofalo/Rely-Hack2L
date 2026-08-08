from django.test import TestCase
from pydantic import ValidationError

from apps.agents.schemas import OrderItemDraft


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
