from django.db import models


class Organization(models.Model):
    """O distribuidor (tenant) dono do catálogo e das conversas."""

    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Customer(models.Model):
    """Cliente B2B do distribuidor (ex.: Mercado Boa Compra)."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="customers"
    )
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=32, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Conversation(models.Model):
    """Uma conversa estilo WhatsApp entre o cliente e o Opero."""

    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="conversations"
    )
    started_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Conversation #{self.pk} · {self.customer}"


class Message(models.Model):
    """Uma mensagem dentro de uma conversa (texto ou áudio transcrito)."""

    class Sender(models.TextChoices):
        CUSTOMER = "customer", "Cliente"
        SYSTEM = "system", "Sistema"

    class Channel(models.TextChoices):
        TEXT = "text", "Texto"
        VOICE = "voice", "Voz"

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    order = models.ForeignKey(
        "core.Order",
        on_delete=models.CASCADE,
        related_name="messages",
        null=True,
        blank=True,
    )
    sender = models.CharField(max_length=16, choices=Sender.choices)
    content = models.TextField(blank=True)
    channel = models.CharField(
        max_length=16, choices=Channel.choices, default=Channel.TEXT
    )
    audio_file = models.FileField(upload_to="messages/audio/", null=True, blank=True)
    transcription = models.TextField(blank=True)
    transcription_confidence = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"[{self.sender}] {self.content[:40]}"


class Order(models.Model):
    """Pedido em construção; o estado principal vive aqui (só o orquestrador altera)."""

    class State(models.TextChoices):
        RECEIVED = "received", "Recebido"
        PARSING = "parsing", "Interpretando"
        MEMORY_LOADED = "memory_loaded", "Memória carregada"
        VALIDATING = "validating", "Validando"
        WAITING_CUSTOMER = "waiting_customer", "Aguardando cliente"
        READY_FOR_CONFIRMATION = "ready_for_confirmation", "Pronto para confirmação"
        CUSTOMER_CONFIRMED = "customer_confirmed", "Confirmado pelo cliente"
        PENDING_APPROVAL = "pending_approval", "Aguardando aprovação"
        SENDING_TO_ERP = "sending_to_erp", "Enviando ao ERP"
        SENT_TO_ERP = "sent_to_erp", "Enviado ao ERP"
        ERP_EXECUTION_FAILED = "erp_execution_failed", "Falha na execução no ERP"

    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="orders"
    )
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="orders"
    )
    state = models.CharField(
        max_length=32, choices=State.choices, default=State.RECEIVED
    )
    current_version = models.ForeignKey(
        "core.OrderVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Order #{self.pk} · {self.get_state_display()}"


class OrderVersion(models.Model):
    """Uma revisão imutável do pedido. Confirmação/aprovação sempre apontam para uma versão exata."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        NEEDS_CLARIFICATION = "needs_clarification", "Precisa de esclarecimento"
        VALIDATED = "validated", "Validado"

    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name="versions"
    )
    version_number = models.PositiveIntegerField()
    status = models.CharField(
        max_length=32, choices=Status.choices, default=Status.DRAFT
    )
    delivery_date = models.DateField(null=True, blank=True)
    missing_fields = models.JSONField(default=list, blank=True)
    clarification_question = models.TextField(blank=True)
    total = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    created_by_agent = models.CharField(max_length=32, blank=True)
    # Snapshot serializado do OrderContext (agents/context.py) nesta versão:
    # items (drafts), hints, resolvedItems, ambiguities, evidence e, quando
    # aplicável, erpReceipt. OrderContext só existe em memória durante uma
    # requisição (agents/context.py, docstring) — este campo é o que permite
    # ao Order API (E7) reconstruir o contexto exato numa requisição seguinte
    # (customer-reply, confirm, approve) sem reprocessar nada do zero.
    context_snapshot = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["version_number"]
        unique_together = [("order", "version_number")]

    def __str__(self):
        return f"Order #{self.order_id} v{self.version_number}"


class OrderItem(models.Model):
    """Um item do pedido, do texto informal até a validação comercial."""

    order_version = models.ForeignKey(
        OrderVersion, on_delete=models.CASCADE, related_name="items"
    )
    raw_text = models.CharField(max_length=255)
    product_hint = models.CharField(max_length=255, blank=True)
    sku = models.CharField(max_length=64, blank=True)
    unit = models.CharField(max_length=32, blank=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    subtotal = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    in_stock = models.BooleanField(null=True, blank=True)
    confidence = models.FloatField(null=True, blank=True)

    def __str__(self):
        return f"{self.raw_text} ({self.sku or 'sem SKU'})"


class CustomerConfirmation(models.Model):
    """Confirmação explícita do cliente, vinculada à versão exata do pedido."""

    order_version = models.OneToOneField(
        OrderVersion, on_delete=models.CASCADE, related_name="customer_confirmation"
    )
    message = models.ForeignKey(
        Message, on_delete=models.SET_NULL, null=True, blank=True
    )
    confirmed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Confirmação · {self.order_version}"


class OperatorApproval(models.Model):
    """Aprovação humana do operador, vinculada à versão exata do pedido."""

    order_version = models.OneToOneField(
        OrderVersion, on_delete=models.CASCADE, related_name="operator_approval"
    )
    approved_by = models.CharField(max_length=255)
    notes = models.TextField(blank=True)
    approved_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Aprovação · {self.order_version}"


class MemoryEntry(models.Model):
    """Memória aprovada cliente ↔ distribuidor (alias de produto ou preferência)."""

    class Kind(models.TextChoices):
        PRODUCT_ALIAS = "product_alias", "Alias de produto"
        PREFERENCE = "preference", "Preferência"

    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="memory_entries"
    )
    kind = models.CharField(max_length=32, choices=Kind.choices)
    product_hint = models.CharField(max_length=255, blank=True)
    sku = models.CharField(max_length=64, blank=True)
    preference_key = models.CharField(max_length=64, blank=True)
    preference_value = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        if self.kind == self.Kind.PRODUCT_ALIAS:
            return f"{self.product_hint} → {self.sku}"
        return f"{self.preference_key} = {self.preference_value}"


class MemoryProposal(models.Model):
    """Alias observado durante um pedido; nunca vira confiável automaticamente."""

    class Status(models.TextChoices):
        PENDING_REVIEW = "pending_review", "Aguardando revisão"
        APPROVED = "approved", "Aprovada"
        REJECTED = "rejected", "Rejeitada"

    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="memory_proposals"
    )
    source_order_version = models.ForeignKey(
        OrderVersion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="memory_proposals",
    )
    alias = models.CharField(max_length=255)
    sku = models.CharField(max_length=64)
    status = models.CharField(
        max_length=32, choices=Status.choices, default=Status.PENDING_REVIEW
    )
    evidence = models.TextField(blank=True)
    reviewed_by = models.CharField(max_length=255, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.alias} → {self.sku} ({self.status})"


class AgentRun(models.Model):
    """Execução de um agente: estado anterior, próximo, motivo e versão (RF37)."""

    class Agent(models.TextChoices):
        ORDER_INTAKE = "order_intake", "Order Intake"
        MEMORY = "memory", "Memory"
        VALIDATION = "validation", "Validation"
        ERP_EXECUTION = "erp_execution", "ERP Execution"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="agent_runs")
    order_version = models.ForeignKey(
        OrderVersion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agent_runs",
    )
    agent_name = models.CharField(max_length=32, choices=Agent.choices)
    previous_state = models.CharField(max_length=32, blank=True)
    next_state = models.CharField(max_length=32, blank=True)
    reason = models.TextField(blank=True)
    success = models.BooleanField(default=True)
    output_summary = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["started_at"]

    def __str__(self):
        return f"{self.agent_name}: {self.previous_state} → {self.next_state}"


class ToolCall(models.Model):
    """Chamada de ferramenta determinística feita por um agente (RF38)."""

    agent_run = models.ForeignKey(
        AgentRun, on_delete=models.CASCADE, related_name="tool_calls"
    )
    tool_name = models.CharField(max_length=64)
    input_data = models.JSONField(default=dict, blank=True)
    output_data = models.JSONField(default=dict, blank=True)
    success = models.BooleanField(default=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.tool_name} ({'ok' if self.success else 'erro'})"
