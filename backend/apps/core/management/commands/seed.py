import random
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from decimal import Decimal

# Importações do app core
from apps.core.models import (
    Organization,
    Customer,
    Conversation,
    MemoryEntry,
    Order,
    Message,
    OrderVersion,
    OrderItem,
    OperatorApproval,
    MemoryProposal,
    CustomerConfirmation,
    AgentRun,
    ToolCall,
)

# Importações do app erp_simulator (assumindo que o nome do app é esse)
from apps.erp_simulator.models import (
    ErpProduct,
    ErpOrder,
    ErpIdempotencyKey,
    ErpInventory,
    ErpPrice,
    ErpAlias,
)


class Command(BaseCommand):
    help = (
        "Popula o banco de dados com dados de mock para desenvolvimento, incluindo ERP."
    )

    def handle(self, *args, **kwargs):
        self.stdout.write("Iniciando a criação de dados de mock...")

        # 1. Limpar dados antigos
        self.stdout.write("Limpando banco de dados atual...")
        Organization.objects.all().delete()
        ErpProduct.objects.all().delete()
        # Nota: Customer, Order, ErpOrder, etc., serão apagados em cascata.

        now = timezone.now()

        # ==========================================
        # DADOS DE MOCK - ERP SIMULATOR
        # ==========================================
        self.stdout.write(
            "Criando dados do ERP (Produtos, Estoque, Preços, Aliases)..."
        )

        produtos_mock = [
            {
                "sku": "CERV-PILSEN-350",
                "name": "Cerveja Pilsen 350ml",
                "unit": "caixa",
                "qty": 100,
                "alias": "breja",
                "price": 60.00,
            },
            {
                "sku": "AGUA-SG-500",
                "name": "Água Mineral SG 500ml",
                "unit": "fardo",
                "qty": 200,
                "alias": "aguinha",
                "price": 15.50,
            },
            {
                "sku": "REFRI-COLA-2L",
                "name": "Refrigerante Cola 2L",
                "unit": "garrafa",
                "qty": 50,
                "alias": "coca",
                "price": 8.99,
            },
            {
                "sku": "SUCO-LAR-1L",
                "name": "Suco de Laranja 1L",
                "unit": "caixa",
                "qty": 30,
                "alias": "sucão",
                "price": 12.00,
            },
            {
                "sku": "ENERG-250",
                "name": "Energético 250ml",
                "unit": "lata",
                "qty": 500,
                "alias": "redbull",
                "price": 11.50,
            },
        ]

        erp_products = []
        for p in produtos_mock:
            # ErpProduct
            prod = ErpProduct.objects.create(
                sku=p["sku"], name=p["name"], unit_label=p["unit"]
            )
            erp_products.append(prod)

            # ErpInventory
            ErpInventory.objects.create(product=prod, quantity_available=p["qty"])

            # ErpAlias
            ErpAlias.objects.create(product=prod, alias_text=p["alias"])

        # ==========================================
        # DADOS DE MOCK - CORE (Clientes e Orgs)
        # ==========================================
        self.stdout.write("Criando Organizações e Clientes...")
        customers = []
        for i in range(1, 6):
            org = Organization.objects.create(name=f"Organização {i} S/A")
            customer = Customer.objects.create(
                name=f"Cliente {i}", phone=f"551199999000{i}", organization=org
            )
            customers.append(customer)

            # Criar preço específico de ERP para este cliente (ErpPrice)
            # Para simplificar, o cliente 'i' tem preço especial no produto 'i'
            ErpPrice.objects.create(
                product=erp_products[i - 1],
                customer=customer,
                unit_price=Decimal(produtos_mock[i - 1]["price"])
                * Decimal("0.9"),  # 10% de desconto
            )

        # ==========================================
        # DADOS DE MOCK - CORE & ERP (Pedidos e Fluxo)
        # ==========================================
        self.stdout.write("Criando fluxo completo de Pedidos, Conversas e Agentes...")
        for i in range(5):
            customer = customers[i]
            product = erp_products[i]
            mock_data = produtos_mock[i]

            # 1. ErpOrder & Idempotency Key (Simulando pedidos passados no ERP)
            erp_order = ErpOrder.objects.create(
                external_order_number=f"EXT-00{i+1}",
                customer=customer,
                status="created",
                items=[{"sku": product.sku, "qty": 2}],
                total=Decimal(mock_data["price"]) * 2,
            )
            ErpIdempotencyKey.objects.create(
                key=f"idem_key_uuid_00{i+1}",
                erp_order=erp_order,
                request_payload={
                    "intent": "create_order",
                    "items": [{"sku": product.sku, "qty": 2}],
                },
            )

            # 2. Memory (MemoryEntry)
            MemoryEntry.objects.create(
                customer=customer,
                kind="product_alias",
                product_hint=mock_data["alias"],
                sku=product.sku,
                notes=f"Cliente costuma chamar {product.name} de {mock_data['alias']}",
            )

            # 3. Conversation & Message
            conv = Conversation.objects.create(customer=customer)
            Message.objects.create(
                conversation=conv,
                sender="customer",
                content=f"Quero pedir 3 {mock_data['unit']}s de {mock_data['alias']}, por favor.",
            )
            msg_sys = Message.objects.create(
                conversation=conv,
                sender="system",
                content="Pedido compreendido. Aguardando sua confirmação.",
            )

            # 4. Order & OrderVersion
            order = Order.objects.create(
                customer=customer, conversation=conv, state="ready_for_confirmation"
            )
            msg_sys.order = order
            msg_sys.save()

            version = OrderVersion.objects.create(
                order=order,
                version_number=1,
                status="validated",
                delivery_date=now.date() + timedelta(days=2),
                total=Decimal(mock_data["price"]) * 3,
                created_by_agent="validation",
            )
            order.current_version = version
            order.save()

            # 5. OrderItem
            OrderItem.objects.create(
                order_version=version,
                raw_text=f"3 {mock_data['unit']}s de {mock_data['alias']}",
                product_hint=product.name,
                sku=product.sku,
                unit=mock_data["unit"],
                quantity=3.00,
                unit_price=Decimal(mock_data["price"]),
                subtotal=Decimal(mock_data["price"]) * 3,
                in_stock=True,
                confidence=0.98,
            )

            # 6. AgentRun & ToolCall
            agent_run = AgentRun.objects.create(
                order=order,
                order_version=version,
                agent_name="validation",
                previous_state="memory_loaded",
                next_state="validating",
                reason="Validando itens em estoque no ERP.",
                success=True,
                output_summary={"valid": True},
            )
            ToolCall.objects.create(
                agent_run=agent_run,
                tool_name="check_erp_inventory",
                input_data={"sku": product.sku},
                output_data={"qty_available": mock_data["qty"]},
                success=True,
            )

            # 7. OperatorApproval & CustomerConfirmation
            OperatorApproval.objects.create(
                order_version=version, approved_by="Admin Central", notes="Validação OK"
            )
            CustomerConfirmation.objects.create(order_version=version, message=msg_sys)

            # 8. MemoryProposal
            MemoryProposal.objects.create(
                customer=customer,
                source_order_version=version,
                alias=f"{mock_data['alias']} gelado",
                sku=product.sku,
                status="pending_review",
                evidence="Identificado novo padrão de fala na mensagem.",
            )

        self.stdout.write(
            self.style.SUCCESS("Dados mockados populados com sucesso para CORE e ERP!")
        )
