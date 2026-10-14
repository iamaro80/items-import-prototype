from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
import shutil
from pathlib import Path
from core.models import ImportJob, ReferenceValue, ServiceItem


class Command(BaseCommand):
    help = "Delete all prototype jobs, uploaded job files, Service Items, and references; then reseed fixtures."

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true", help="Acknowledge deletion of all prototype data.")

    def handle(self, *args, **options):
        if not options["yes"]:
            raise CommandError("Pass --yes after reviewing which prototype data this command deletes.")
        for job in ImportJob.objects.all():
            job.source_file.delete(save=False)
        ImportJob.objects.all().delete()
        ServiceItem.objects.all().delete()
        ReferenceValue.objects.filter(parent__isnull=False).delete()
        ReferenceValue.objects.all().delete()
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)
        Path(settings.MEDIA_ROOT).mkdir(parents=True, exist_ok=True)
        call_command("seed_demo")
        self.stdout.write(self.style.SUCCESS("Prototype data reset. Original source files remain unchanged."))
