from django.contrib import admin

from apps.erp_simulator.models import (
    ErpAlias,
    ErpIdempotencyKey,
    ErpInventory,
    ErpOrder,
    ErpPrice,
    ErpProduct,
)

admin.site.register(ErpProduct)
admin.site.register(ErpAlias)
admin.site.register(ErpPrice)
admin.site.register(ErpInventory)
admin.site.register(ErpOrder)
admin.site.register(ErpIdempotencyKey)
