from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.core.urls")),
    path("api/erp/", include("apps.erp_simulator.urls")),
]

# Áudio de evidência (Message.audio_file, E9 / RF45) servido pelo próprio
# Django, inclusive com DEBUG=false. Num sistema real isso seria um bucket
# com URL própria; enquanto não é, servir daqui é o que mantém a evidência
# de voz acessível no deploy. Note que `conf.urls.static.static()` não serve:
# ele devolve lista vazia quando DEBUG=false.
urlpatterns += [
    re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
]
