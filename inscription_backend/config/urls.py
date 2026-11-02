from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from inscriptions.views import ApplicationImageServeView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("inscriptions.urls")),
    path(
        "media/application-images/<path:filename>",
        ApplicationImageServeView.as_view(),
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
