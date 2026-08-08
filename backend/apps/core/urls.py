from django.urls import path

from apps.core.views import (
    DemoResetView,
    OrderApproveView,
    OrderConfirmView,
    OrderCustomerReplyView,
    OrderDetailView,
    OrderIngestView,
    OrderTimelineView,
    health,
)

urlpatterns = [
    path("health/", health, name="health"),
    path("orders/ingest/", OrderIngestView.as_view(), name="order-ingest"),
    path("orders/<int:pk>/", OrderDetailView.as_view(), name="order-detail"),
    path(
        "orders/<int:pk>/customer-reply/",
        OrderCustomerReplyView.as_view(),
        name="order-customer-reply",
    ),
    path("orders/<int:pk>/confirm/", OrderConfirmView.as_view(), name="order-confirm"),
    path("orders/<int:pk>/approve/", OrderApproveView.as_view(), name="order-approve"),
    path("orders/<int:pk>/timeline/", OrderTimelineView.as_view(), name="order-timeline"),
    path("demo/reset/", DemoResetView.as_view(), name="demo-reset"),
]
