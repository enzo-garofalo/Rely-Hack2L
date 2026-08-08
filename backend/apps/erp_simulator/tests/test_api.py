from django.conf import settings
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from apps.core.models import Customer
from apps.erp_simulator.models import ErpIdempotencyKey, ErpOrder


class ErpApiTests(TestCase):
    def setUp(self):
        call_command("seed_demo", verbosity=0)
        self.client = APIClient()
        self.customer = Customer.objects.get(name="Mercado Boa Compra")
        self.auth = {"HTTP_X_API_KEY": settings.ERP_API_KEY}

    def test_context_requires_api_key_and_returns_frozen_commercial_data(self):
        denied = self.client.get(f"/api/erp/context/{self.customer.id}/")
        response = self.client.get(
            f"/api/erp/context/{self.customer.id}/", **self.auth
        )

        self.assertEqual(denied.status_code, 403)
        self.assertEqual(response.status_code, 200)
        catalog = {item["sku"]: item for item in response.json()["catalog"]}
        self.assertEqual(len(catalog), 6)
        self.assertEqual(catalog["COCA-2L-CX6"]["price"], 54.0)
        self.assertEqual(catalog["COCA-2L-CX6"]["quantity_available"], 80)
        self.assertEqual(catalog["COCA-ZERO-LATA-CX12"]["price"], 42.0)
        self.assertEqual(catalog["OLEO-SOJA-900ML-CX20"]["price"], 118.0)

    def test_order_creation_is_idempotent_for_retries(self):
        payload = {
            "customer": self.customer.id,
            "items": [{"sku": "COCA-2L-CX6", "quantity": 10, "unit_price": 54, "subtotal": 540}],
            "total": "540.00",
        }
        headers = {**self.auth, "HTTP_IDEMPOTENCY_KEY": "test-order-v1"}

        first = self.client.post("/api/erp/orders/", payload, format="json", **headers)
        second = self.client.post("/api/erp/orders/", payload, format="json", **headers)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["external_order_number"], second.json()["external_order_number"])
        self.assertEqual(ErpOrder.objects.count(), 1)
        self.assertEqual(ErpIdempotencyKey.objects.count(), 1)

    def test_order_creation_requires_idempotency_key(self):
        response = self.client.post(
            "/api/erp/orders/",
            {"customer": self.customer.id, "items": [], "total": "0.00"},
            format="json",
            **self.auth,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Idempotency-Key", response.json()["detail"])
