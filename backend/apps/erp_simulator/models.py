from django.db import models

from apps.core.models import Customer


class ErpProduct(models.Model):
    """Catálogo do ERP simulado — única fonte de SKUs válidos."""

    sku = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    unit_label = models.CharField(max_length=64, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.sku} · {self.name}"


class ErpAlias(models.Model):
    """Sinônimo/apelido do catálogo (ex.: "zero" → COCA-ZERO-LATA-CX12) usado pelo search_catalog."""

    product = models.ForeignKey(
        ErpProduct, on_delete=models.CASCADE, related_name="aliases"
    )
    alias_text = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("product", "alias_text")]

    def __str__(self):
        return f"{self.alias_text} → {self.product.sku}"


class ErpPrice(models.Model):
    """Preço por cliente (RF14)."""

    product = models.ForeignKey(
        ErpProduct, on_delete=models.CASCADE, related_name="prices"
    )
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="erp_prices"
    )
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("product", "customer")]

    def __str__(self):
        return f"{self.product.sku} · {self.customer} · R$ {self.unit_price}"


class ErpInventory(models.Model):
    """Estoque disponível por produto."""

    product = models.OneToOneField(
        ErpProduct, on_delete=models.CASCADE, related_name="inventory"
    )
    quantity_available = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.product.sku}: {self.quantity_available}"


class ErpOrder(models.Model):
    """Pedido criado no ERP (system of record). Único ponto de escrita comercial."""

    class Status(models.TextChoices):
        CREATED = "created", "Criado"
        CANCELLED = "cancelled", "Cancelado"

    external_order_number = models.CharField(max_length=64, unique=True)
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="erp_orders"
    )
    status = models.CharField(
        max_length=32, choices=Status.choices, default=Status.CREATED
    )
    items = models.JSONField(default=list)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.external_order_number


class ErpIdempotencyKey(models.Model):
    """Garante que POST /api/erp/orders com a mesma chave nunca crie um pedido duplicado (RF28-29, RF35)."""

    key = models.CharField(max_length=128, unique=True)
    erp_order = models.ForeignKey(
        ErpOrder, on_delete=models.CASCADE, related_name="idempotency_keys"
    )
    request_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.key} → {self.erp_order.external_order_number}"
