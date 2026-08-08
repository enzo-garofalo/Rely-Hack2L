from django.urls import path

from apps.core.views import (
    DemoResetView,
    OrderApproveView,
    OrderConfirmView,
    OrderCustomerReplyView,
    OrderDetailView,
    OrderIngestAudioView,
    OrderIngestView,
    OrderTimelineView,
    OrderVoiceReplyView,
    WhatsAppInboundView,
    health,
)

urlpatterns = [
    path("health/", health, name="health"),
    path("orders/ingest/", OrderIngestView.as_view(), name="order-ingest"),
    path("orders/ingest-audio/", OrderIngestAudioView.as_view(), name="order-ingest-audio"),
    path("orders/<int:pk>/", OrderDetailView.as_view(), name="order-detail"),
    path(
        "orders/<int:pk>/customer-reply/",
        OrderCustomerReplyView.as_view(),
        name="order-customer-reply",
    ),
    path("orders/<int:pk>/confirm/", OrderConfirmView.as_view(), name="order-confirm"),
    path("orders/<int:pk>/approve/", OrderApproveView.as_view(), name="order-approve"),
    path("orders/<int:pk>/timeline/", OrderTimelineView.as_view(), name="order-timeline"),
    path("orders/<int:pk>/voice-reply/", OrderVoiceReplyView.as_view(), name="order-voice-reply"),
    # Borda do WhatsApp real (E10): só o gateway Node chama esta rota.
    path("whatsapp/inbound/", WhatsAppInboundView.as_view(), name="whatsapp-inbound"),
    path("demo/reset/", DemoResetView.as_view(), name="demo-reset"),
]
