from django.contrib import admin

from apps.core.models import (
    AgentRun,
    Conversation,
    Customer,
    CustomerConfirmation,
    MemoryEntry,
    MemoryProposal,
    Message,
    OperatorApproval,
    Order,
    OrderItem,
    OrderVersion,
    Organization,
    ToolCall,
)

admin.site.register(Organization)
admin.site.register(Customer)
admin.site.register(Conversation)
admin.site.register(Message)
admin.site.register(Order)
admin.site.register(OrderVersion)
admin.site.register(OrderItem)
admin.site.register(CustomerConfirmation)
admin.site.register(OperatorApproval)
admin.site.register(MemoryEntry)
admin.site.register(MemoryProposal)
admin.site.register(AgentRun)
admin.site.register(ToolCall)
