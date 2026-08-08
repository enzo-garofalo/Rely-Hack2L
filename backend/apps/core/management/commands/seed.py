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

        # Produtos reais de mercado (alimentos/insumos de restaurante) com marcas no alias
        produtos_mock = [
            {
                "sku": "ARROZ-T1-5KG",
                "name": "Arroz Agulhinha Tipo 1 5kg",
                "unit": "pacote",
                "qty": 300,
                "alias": "Tio João",
                "price": 26.50,
            },
            {
                "sku": "FEIJAO-CAR-1KG",
                "name": "Feijão Carioca 1kg",
                "unit": "pacote",
                "qty": 200,
                "alias": "Camil",
                "price": 8.90,
            },
            {
                "sku": "MAC-ESP-500G",
                "name": "Macarrão Espaguete 8 500g",
                "unit": "pacote",
                "qty": 150,
                "alias": "Barilla",
                "price": 6.50,
            },
            {
                "sku": "MOLHO-TOM-340G",
                "name": "Molho de Tomate Tradicional 340g",
                "unit": "sachê",
                "qty": 400,
                "alias": "Pomarola",
                "price": 3.20,
            },
            {
                "sku": "OLEO-SOJA-900ML",
                "name": "Óleo de Soja Refinado 900ml",
                "unit": "garrafa",
                "qty": 500,
                "alias": "Liza",
                "price": 5.90,
            },
            {
                "sku": "AZEITE-EV-500ML",
                "name": "Azeite de Oliva Extra Virgem 500ml",
                "unit": "garrafa",
                "qty": 100,
                "alias": "Gallo",
                "price": 35.90,
            },
            {
                "sku": "FARINHA-TRI-1KG",
                "name": "Farinha de Trigo Tradicional 1kg",
                "unit": "pacote",
                "qty": 250,
                "alias": "Dona Benta",
                "price": 5.40,
            },
            {
                "sku": "LEITE-COND-395G",
                "name": "Leite Condensado Integral 395g",
                "unit": "lata",
                "qty": 600,
                "alias": "Leite Moça",
                "price": 7.90,
            },
            {
                "sku": "CREME-LEITE-200G",
                "name": "Creme de Leite Leve 200g",
                "unit": "caixa",
                "qty": 550,
                "alias": "Creme de leite Nestlé",
                "price": 4.50,
            },
            {
                "sku": "MAIONESE-500G",
                "name": "Maionese Tradicional Pote 500g",
                "unit": "pote",
                "qty": 180,
                "alias": "Hellmann's",
                "price": 10.90,
            },
            {
                "sku": "KETCHUP-TRAD-400G",
                "name": "Ketchup Tradicional 400g",
                "unit": "frasco",
                "qty": 220,
                "alias": "Heinz",
                "price": 12.50,
            },
            {
                "sku": "MOSTARDA-AM-200G",
                "name": "Mostarda Amarela 200g",
                "unit": "frasco",
                "qty": 150,
                "alias": "Hemmer",
                "price": 8.90,
            },
            {
                "sku": "CALDO-GAL-114G",
                "name": "Caldo de Galinha em Cubos 114g",
                "unit": "caixa",
                "qty": 300,
                "alias": "Knorr",
                "price": 4.10,
            },
            {
                "sku": "BATATA-PALHA-140G",
                "name": "Batata Palha Extrafina 140g",
                "unit": "pacote",
                "qty": 250,
                "alias": "Yoki",
                "price": 9.90,
            },
            {
                "sku": "QUEIJO-PARM-50G",
                "name": "Queijo Parmesão Ralado 50g",
                "unit": "pacote",
                "qty": 400,
                "alias": "Faixa Azul",
                "price": 7.50,
            },
            {
                "sku": "REQUEIJAO-200G",
                "name": "Requeijão Cremoso Tradicional 200g",
                "unit": "copo",
                "qty": 320,
                "alias": "Catupiry",
                "price": 9.50,
            },
            {
                "sku": "MANTEIGA-SAL-200G",
                "name": "Manteiga com Sal Pote 200g",
                "unit": "pote",
                "qty": 200,
                "alias": "Manteiga Aviação",
                "price": 13.90,
            },
            {
                "sku": "ACHOCOLATADO-400G",
                "name": "Achocolatado em Pó 400g",
                "unit": "lata",
                "qty": 350,
                "alias": "Nescau",
                "price": 8.99,
            },
            {
                "sku": "LING-CALAB-400G",
                "name": "Linguiça Calabresa Defumada 400g",
                "unit": "pacote",
                "qty": 120,
                "alias": "Sadia",
                "price": 18.90,
            },
            {
                "sku": "HAMBURGUER-BOV-672G",
                "name": "Hambúrguer Bovino Caixa 672g",
                "unit": "caixa",
                "qty": 90,
                "alias": "Seara",
                "price": 22.90,
            },
            {
                "sku": "PAO-FORMA-500G",
                "name": "Pão de Forma Tradicional 500g",
                "unit": "pacote",
                "qty": 150,
                "alias": "Pullman",
                "price": 6.80,
            },
            {
                "sku": "MISTURA-BOLO-400G",
                "name": "Mistura para Bolo Sabor Chocolate 400g",
                "unit": "pacote",
                "qty": 200,
                "alias": "Fleischmann",
                "price": 5.50,
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
        num_mock_items = len(produtos_mock)

        for i in range(1, num_mock_items + 1):
            org = Organization.objects.create(name=f"Restaurante/Empresa {i} S/A")
            customer = Customer.objects.create(
                name=f"Cliente {i}", phone=f"551199999{(i):04d}", organization=org
            )
            customers.append(customer)

            # Criar preço específico de ERP para este cliente (ErpPrice)
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

        for i in range(num_mock_items):
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
                alias=f"{mock_data['alias']} original",
                sku=product.sku,
                status="pending_review",
                evidence="Identificado novo padrão de fala na mensagem.",
            )

        self.stdout.write(
            self.style.SUCCESS("Dados mockados populados com sucesso para CORE e ERP!")
        )
