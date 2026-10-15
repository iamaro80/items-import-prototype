from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.db import transaction
import shutil
from pathlib import Path
from core.models import (Facility, ImportAuditEvent, ImportJob,
                         ImportMappingTemplate, ReferenceValue, ServiceItem)


class Command(BaseCommand):
    help = "Restore the prototype to its first-run state with only starter facilities and references."

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true", help="Acknowledge deletion of all prototype data.")

    def handle(self, *args, **options):
        if not options["yes"]:
            raise CommandError("Pass --yes after reviewing which prototype data this command deletes.")
        if ImportJob.objects.filter(state__in=["validating", "importing"]).exists():
            raise CommandError("An import is running. Wait for it to finish or cancel it before resetting.")
        with transaction.atomic():
            ImportAuditEvent.objects.all().delete()
            ImportJob.objects.all().delete()
            ImportMappingTemplate.objects.all().delete()
            ServiceItem.objects.all().delete()
            ReferenceValue.objects.filter(parent__isnull=False).delete()
            ReferenceValue.objects.all().delete()
            Facility.objects.all().delete()
            call_command("seed_demo", verbosity=0)
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)
        Path(settings.MEDIA_ROOT).mkdir(parents=True, exist_ok=True)
        self.stdout.write(self.style.SUCCESS("First-run demo state restored. Original sample files remain unchanged."))
