from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import Customer

from .models import ErpIdempotencyKey, ErpOrder, ErpProduct
from .permissions import HasErpApiKey
from .serializers import (
    ErpContextCustomerSerializer,
    ErpOrderCreateSerializer,
    ErpOrderSerializer,
    ErpProductCatalogSerializer,
)


def _next_external_order_number():
    year = timezone.now().year
    prefix = f"ERP-{year}-"
    seq = ErpOrder.objects.filter(external_order_number__startswith=prefix).count() + 1
    return f"{prefix}{seq:04d}"


class ErpContextView(APIView):
    """GET /api/erp/context/{customerId} — cliente + catálogo + preços + estoque (RF32)."""

    permission_classes = [HasErpApiKey]

    def get(self, request, customer_id):
        customer = get_object_or_404(Customer, pk=customer_id)
        products = (
            ErpProduct.objects.filter(active=True)
            .select_related("inventory")
            .prefetch_related("prices", "aliases")
        )
        catalog = ErpProductCatalogSerializer(
            products, many=True, context={"customer": customer}
        ).data
        return Response(
            {
                "customer": ErpContextCustomerSerializer(customer).data,
                "catalog": catalog,
            }
        )


class ErpOrderListCreateView(APIView):
    """POST /api/erp/orders — cria pedido, exige Idempotency-Key (RF33-35)."""

    permission_classes = [HasErpApiKey]

    def post(self, request):
        idempotency_key = request.headers.get("Idempotency-Key")
        if not idempotency_key:
            return Response(
                {"detail": "Header Idempotency-Key é obrigatório."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        existing = ErpIdempotencyKey.objects.select_related("erp_order").filter(
            key=idempotency_key
        ).first()
        if existing:
            return Response(
                ErpOrderSerializer(existing.erp_order).data, status=status.HTTP_200_OK
            )

        serializer = ErpOrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        erp_order = ErpOrder.objects.create(
            external_order_number=_next_external_order_number(),
            customer=serializer.validated_data["customer"],
            items=serializer.validated_data["items"],
            total=serializer.validated_data["total"],
        )
        ErpIdempotencyKey.objects.create(
            key=idempotency_key,
            erp_order=erp_order,
            request_payload=request.data,
        )
        return Response(
            ErpOrderSerializer(erp_order).data, status=status.HTTP_201_CREATED
        )


class ErpOrderDetailView(APIView):
    """GET /api/erp/orders/{id} — recibo do pedido (RF34)."""

    permission_classes = [HasErpApiKey]

    def get(self, request, pk):
        erp_order = get_object_or_404(ErpOrder, pk=pk)
        return Response(ErpOrderSerializer(erp_order).data)
