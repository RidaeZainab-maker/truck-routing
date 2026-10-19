"""Serve the built React app's index.html (single-container deploy only)."""
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.http import require_GET


@require_GET
@never_cache  # index.html must not be cached; the hashed /assets/* it references are.
@xframe_options_exempt  # Hugging Face shows the Space inside an iframe on huggingface.co
def spa_index(request):
    html = (settings.FRONTEND_DIST / 'index.html').read_bytes()
    return HttpResponse(html, content_type='text/html; charset=utf-8')
