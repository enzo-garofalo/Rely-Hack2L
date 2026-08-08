from rest_framework import serializers

from apps.core.models import Customer

from .models import ErpOrder, ErpProduct


class ErpContextCustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ["id", "name", "phone"]


class ErpProductCatalogSerializer(serializers.ModelSerializer):
    """Produto do catálogo com preço do cliente (se houver) e estoque atual."""

    price = serializers.SerializerMethodField()
    quantity_available = serializers.SerializerMethodField()
    aliases = serializers.SerializerMethodField()

    class Meta:
        model = ErpProduct
        fields = ["sku", "name", "unit_label", "price", "quantity_available", "aliases"]

    def get_price(self, obj):
        customer = self.context.get("customer")
        price = next(
            (p for p in obj.prices.all() if p.customer_id == customer.id), None
        )
        return float(price.unit_price) if price else None

    def get_quantity_available(self, obj):
        inventory = getattr(obj, "inventory", None)
        return inventory.quantity_available if inventory else 0

    def get_aliases(self, obj):
        return [alias.alias_text for alias in obj.aliases.all()]


class ErpOrderItemSerializer(serializers.Serializer):
    sku = serializers.CharField()
    quantity = serializers.FloatField()
    unit_price = serializers.FloatField(required=False, allow_null=True)
    subtotal = serializers.FloatField(required=False, allow_null=True)


class ErpOrderCreateSerializer(serializers.Serializer):
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.all())
    items = ErpOrderItemSerializer(many=True)
    total = serializers.DecimalField(max_digits=12, decimal_places=2)


class ErpOrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErpOrder
        fields = [
            "id",
            "external_order_number",
            "customer",
            "status",
            "items",
            "total",
            "created_at",
        ]
