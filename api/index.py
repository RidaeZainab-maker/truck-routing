"""Vercel Python function: the Django backend (WSGI) behind /api/*.

vercel.json rewrites /api/(.*) here; Django still sees the original path
(/api/health, /api/routes), so backend/config/urls.py works unchanged.
"""
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # the function filesystem is read-only (except /tmp)

BACKEND = Path(__file__).resolve().parent.parent / 'backend'
sys.path.insert(0, str(BACKEND))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

from config.wsgi import application  # noqa: E402

app = application
