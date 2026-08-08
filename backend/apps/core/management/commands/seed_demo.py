"""Create the deterministic dataset used by the end-to-end demo."""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.core.models import Customer, MemoryEntry, Organization
from apps.erp_simulator.models import ErpAlias, ErpInventory, ErpPrice, ErpProduct


DEMO_PRODUCTS = (
    {
        "sku": "COCA-2L-CX6",
        "name": "Coca-Cola Original 2L",
        "unit": "caixa com 6",
        "price": "54.00",
        "stock": 80,
        "aliases": ("coca 2L", "caixa de coca 2 litros"),
    },
    {
        "sku": "COCA-ZERO-LATA-CX12",
        "name": "Coca-Cola Sem Açúcar Lata 350ml",
        "unit": "fardo com 12",
        "price": "42.00",
        "stock": 45,
        "aliases": ("coca zero lata", "fardo de coca zero"),
    },
    {
        "sku": "OLEO-SOJA-900ML-CX20",
        "name": "Óleo de Soja 900ml",
        "unit": "caixa com 20",
        "price": "118.00",
        "stock": 30,
        "aliases": ("óleo de soja", "óleo 900ml"),
    },
    {
        "sku": "CERV-PILSEN-350-CX12",
        "name": "Cerveja Pilsen Lata 350ml",
        "unit": "caixa com 12",
        "price": "60.00",
        "stock": 100,
        "aliases": ("cerveja pilsen",),
    },
    {
        "sku": "AGUA-SG-500-FD12",
        "name": "Água Mineral sem Gás 500ml",
        "unit": "fardo com 12",
        "price": "15.50",
        "stock": 200,
        "aliases": ("água sem gás",),
    },
    {
        "sku": "SUCO-LAR-1L-CX6",
        "name": "Suco de Laranja 1L",
        "unit": "caixa com 6",
        "price": "72.00",
        "stock": 30,
        "aliases": ("suco de laranja",),
    },
)


class Command(BaseCommand):
    help = "Restaura o dataset congelado e determinístico da demo do Opero."

    @transaction.atomic
    def handle(self, *args, **options):
        # Both roots cascade through all volatile order, agent and ERP data.
        # Deleting instead of update_or_create also removes stale rows from old seeds.
        Organization.objects.all().delete()
        ErpProduct.objects.all().delete()

        organization = Organization.objects.create(name="Distribuidora Opero")
        customer = Customer.objects.create(
            organization=organization,
            name="Mercado Boa Compra",
            phone="5511999990001",
        )

        for item in DEMO_PRODUCTS:
            product = ErpProduct.objects.create(
                sku=item["sku"],
                name=item["name"],
                unit_label=item["unit"],
            )
            ErpInventory.objects.create(
                product=product,
                quantity_available=item["stock"],
            )
            ErpPrice.objects.create(
                product=product,
                customer=customer,
                unit_price=Decimal(item["price"]),
            )
            ErpAlias.objects.bulk_create(
                [ErpAlias(product=product, alias_text=alias) for alias in item["aliases"]]
            )

        MemoryEntry.objects.bulk_create(
            [
                MemoryEntry(
                    customer=customer,
                    kind=MemoryEntry.Kind.PRODUCT_ALIAS,
                    product_hint="coca 2L",
                    sku="COCA-2L-CX6",
                    notes="Cliente costuma comprar Coca-Cola 2L em caixa com 6.",
                ),
                MemoryEntry(
                    customer=customer,
                    kind=MemoryEntry.Kind.PRODUCT_ALIAS,
                    product_hint="óleo da última vez",
                    sku="OLEO-SOJA-900ML-CX20",
                    notes="Último óleo comprado pelo cliente.",
                ),
                MemoryEntry(
                    customer=customer,
                    kind=MemoryEntry.Kind.PREFERENCE,
                    preference_key="delivery_period",
                    preference_value="morning",
                    notes="Cliente aceita entrega pela manhã.",
                ),
            ]
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Dataset da demo restaurado: 1 cliente, 6 produtos e 3 memórias aprovadas."
            )
        )
