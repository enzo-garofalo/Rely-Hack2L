from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.core.urls")),
    path("api/erp/", include("apps.erp_simulator.urls")),
]

if settings.DEBUG:
    # Áudio de evidência (Message.audio_file, E9) servido localmente só em
    # dev/demo — em produção isso seria um bucket com URL própria.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
