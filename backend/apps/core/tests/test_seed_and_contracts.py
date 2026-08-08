from django.core.management import call_command
from django.test import TestCase

from apps.core.models import (
    Conversation,
    Customer,
    MemoryEntry,
    MemoryProposal,
    Order,
    OrderVersion,
    Organization,
)
from apps.core.serializers import serialize_order
from apps.core import order_service
from apps.agents.schemas import ErpReceipt
from apps.erp_simulator.models import ErpInventory, ErpPrice, ErpProduct


class DemoSeedTests(TestCase):
    def dataset_snapshot(self):
        return {
            "organizations": list(Organization.objects.values_list("name", flat=True)),
            "customers": list(Customer.objects.values_list("name", "phone")),
            "products": list(
                ErpProduct.objects.order_by("sku").values_list("sku", "unit_label")
            ),
            "prices": list(
                ErpPrice.objects.order_by("product__sku").values_list(
                    "product__sku", "unit_price"
                )
            ),
            "inventory": list(
                ErpInventory.objects.order_by("product__sku").values_list(
                    "product__sku", "quantity_available"
                )
            ),
            "memories": list(
                MemoryEntry.objects.order_by("kind", "product_hint").values_list(
                    "kind", "product_hint", "sku", "preference_key", "preference_value"
                )
            ),
        }

    def test_seed_demo_is_repeatable_and_matches_the_frozen_scenario(self):
        call_command("seed_demo", verbosity=0)
        first = self.dataset_snapshot()
        call_command("seed_demo", verbosity=0)

        self.assertEqual(self.dataset_snapshot(), first)
        self.assertEqual(first["organizations"], ["Distribuidora Opero"])
        self.assertEqual(first["customers"], [("Mercado Boa Compra", "5511999990001")])
        self.assertEqual(len(first["products"]), 6)
        self.assertEqual(len(first["prices"]), 6)
        self.assertEqual(len(first["inventory"]), 6)
        self.assertEqual(len(first["memories"]), 3)
        self.assertIn(("COCA-2L-CX6", "caixa com 6"), first["products"])
        self.assertIn(("COCA-ZERO-LATA-CX12", "fardo com 12"), first["products"])
        self.assertIn(("OLEO-SOJA-900ML-CX20", "caixa com 20"), first["products"])

    def test_legacy_seed_alias_keeps_the_same_contract(self):
        call_command("seed", verbosity=0)
        self.assertEqual(Customer.objects.get().name, "Mercado Boa Compra")
        self.assertEqual(ErpProduct.objects.count(), 6)


class OrderSerializationTests(TestCase):
    def test_order_contract_exposes_item_confidence_and_nullable_values(self):
        organization = Organization.objects.create(name="Distribuidora")
        customer = Customer.objects.create(organization=organization, name="Mercado")
        conversation = Conversation.objects.create(customer=customer)
        order = Order.objects.create(customer=customer, conversation=conversation)
        version = OrderVersion.objects.create(
            order=order,
            version_number=1,
            status=OrderVersion.Status.VALIDATED,
            total="54.00",
            context_snapshot={
                "items": [{
                    "id": "item-1",
                    "rawText": "uma caixa de coca 2L",
                    "productGuess": "coca 2L",
                    "quantity": 1,
                    "unit": "caixa",
                    "confidence": 0.93,
                }],
                "resolvedItems": [{
                    "itemRef": "item-1",
                    "sku": "COCA-2L-CX6",
                    "unit": "caixa com 6",
                    "unitPrice": 54,
                    "inStock": True,
                }],
            },
        )
        order.current_version = version
        order.state = Order.State.READY_FOR_CONFIRMATION
        order.save(update_fields=["current_version", "state"])

        item = serialize_order(order)["currentVersion"]["items"][0]

        self.assertEqual(item["confidence"], 0.93)
        self.assertEqual(item["sku"], "COCA-2L-CX6")
        self.assertEqual(item["subtotal"], 54)
        self.assertTrue(item["inStock"])

    def test_public_receipt_contract_maps_external_id_and_keeps_payload(self):
        organization = Organization.objects.create(name="Distribuidora")
        customer = Customer.objects.create(organization=organization, name="Mercado")
        conversation = Conversation.objects.create(customer=customer)
        order = Order.objects.create(customer=customer, conversation=conversation)
        receipt = ErpReceipt(
            externalOrderId="ERP-2026-0001",
            idempotencyKey="order-1-1",
            payload={"customerId": customer.id, "items": []},
        )
        version = OrderVersion.objects.create(
            order=order,
            version_number=1,
            status=OrderVersion.Status.VALIDATED,
            context_snapshot={"erpReceipt": receipt.model_dump(mode="json")},
        )
        order.current_version = version
        order.state = Order.State.SENT_TO_ERP
        order.save(update_fields=["current_version", "state"])

        public_receipt = serialize_order(order)["currentVersion"]["erpReceipt"]

        self.assertEqual(public_receipt["erpOrderId"], "ERP-2026-0001")
        self.assertNotIn("externalOrderId", public_receipt)
        self.assertEqual(public_receipt["payload"]["customerId"], customer.id)


class MemoryProposalFlowTests(TestCase):
    def test_resolved_customer_reply_creates_a_pending_review_proposal(self):
        call_command("seed_demo", verbosity=0)
        customer = Customer.objects.get(name="Mercado Boa Compra")
        conversation = Conversation.objects.create(customer=customer)
        order = Order.objects.create(
            customer=customer,
            conversation=conversation,
            state=Order.State.WAITING_CUSTOMER,
        )
        version = OrderVersion.objects.create(
            order=order,
            version_number=1,
            status=OrderVersion.Status.NEEDS_CLARIFICATION,
            context_snapshot={
                "items": [{
                    "id": "item-zero",
                    "rawText": "6 fardos da zero",
                    "productGuess": "zero",
                    "quantity": 6,
                    "unit": "fardo",
                    "confidence": 0.62,
                }],
                "resolvedItems": [],
                "ambiguities": [{
                    "itemRef": "item-zero",
                    "ambiguities": [{
                        "field": "sku",
                        "question": "A Coca Zero é o fardo com 12 latas?",
                        "candidates": ["COCA-ZERO-LATA-CX12"],
                    }],
                }],
            },
        )
        order.current_version = version
        order.save(update_fields=["current_version"])

        outcome = order_service.submit_customer_reply(
            order_id=order.id,
            item_ref="item-zero",
            message="Sim, a lata 350ml em fardo com 12.",
        )

        proposal = MemoryProposal.objects.get()
        self.assertEqual(outcome.order.state, Order.State.READY_FOR_CONFIRMATION)
        self.assertEqual(proposal.alias, "fardo da zero")
        self.assertEqual(proposal.sku, "COCA-ZERO-LATA-CX12")
        self.assertEqual(proposal.status, MemoryProposal.Status.PENDING_REVIEW)
        self.assertEqual(proposal.evidence, "Sim, a lata 350ml em fardo com 12.")
        self.assertEqual(proposal.source_order_version_id, outcome.order.current_version_id)
