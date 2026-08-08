from django.urls import path

from .views import ErpContextView, ErpOrderDetailView, ErpOrderListCreateView

urlpatterns = [
    path("context/<int:customer_id>/", ErpContextView.as_view(), name="erp-context"),
    path("orders/", ErpOrderListCreateView.as_view(), name="erp-orders"),
    path("orders/<int:pk>/", ErpOrderDetailView.as_view(), name="erp-order-detail"),
]
