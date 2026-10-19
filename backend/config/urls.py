from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('routing.urls')),
]

if settings.FRONTEND_DIST:
    from .spa import spa_index

    # SPA fallback: any non-API, non-admin, non-static, non-asset path gets index.html (real files
    # under the dist folder are served earlier by WhiteNoise).
    urlpatterns.append(re_path(r'^(?!api/|admin/|static/|assets/).*$', spa_index))
