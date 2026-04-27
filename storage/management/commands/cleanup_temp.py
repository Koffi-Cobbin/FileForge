"""Manual / scheduled cleanup of orphaned temp upload files."""
from __future__ import annotations

from django.core.management.base import BaseCommand

from storage.utils import cleanup_orphaned_temp_files


class Command(BaseCommand):
    help = "Delete orphaned temp upload files older than --max-age seconds."

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-age",
            type=int,
            default=24 * 3600,
            help="Maximum age in seconds (default: 86400).",
        )

    def handle(self, *args, **options):
        removed = cleanup_orphaned_temp_files(options["max_age"])
        self.stdout.write(
            self.style.SUCCESS(f"Removed {removed} orphaned temp file(s).")
        )
