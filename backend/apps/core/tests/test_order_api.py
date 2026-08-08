from django.test import TestCase
from rest_framework.test import APIClient

from apps.core.models import Conversation, Customer, Order, Organization


class OrderApiGuardTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        organization = Organization.objects.create(name="Distribuidora")
        self.customer = Customer.objects.create(organization=organization, name="Mercado")
        conversation = Conversation.objects.create(customer=self.customer)
        self.order = Order.objects.create(customer=self.customer, conversation=conversation)

    def test_health_and_ingest_input_contract(self):
        self.assertEqual(self.client.get("/api/health/").status_code, 200)

        missing = self.client.post("/api/orders/ingest/", {}, format="json")
        unknown = self.client.post(
            "/api/orders/ingest/",
            {"customerId": 999999, "message": "pedido"},
            format="json",
        )

        self.assertEqual(missing.status_code, 400)
        self.assertEqual(missing.json()["detail"], "customerId e message são obrigatórios.")
        self.assertEqual(unknown.status_code, 404)

    def test_customer_reply_without_pending_clarification_is_rejected(self):
        response = self.client.post(
            f"/api/orders/{self.order.id}/customer-reply/",
            {"message": "sim"},
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("não há esclarecimento pendente", response.json()["detail"])

    def test_confirm_and_approve_are_rejected_in_the_wrong_state(self):
        confirm = self.client.post(f"/api/orders/{self.order.id}/confirm/", {}, format="json")
        approve = self.client.post(
            f"/api/orders/{self.order.id}/approve/",
            {"approvedBy": "Pedro"},
            format="json",
        )

        self.assertEqual(confirm.status_code, 409)
        self.assertEqual(approve.status_code, 409)

    def test_approval_requires_operator_identity(self):
        response = self.client.post(
            f"/api/orders/{self.order.id}/approve/", {}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "approvedBy é obrigatório.")
