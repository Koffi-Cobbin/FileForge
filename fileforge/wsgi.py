"""WSGI config for FileForge."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fileforge.settings")

application = get_wsgi_application()
