import time
from collections import Counter
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.db.models import Count, Q
from django.utils import timezone
from core.engine import create_approved_references, import_row, validate_row
from core.models import ImportIssue, ImportJob, ImportRow, ImportReferenceResolution
from core.schema import normalize, PARENT_FIELDS


def recount(job):
    counts = dict(ImportRow.objects.filter(job=job).values_list("import_status").annotate(n=Count("id")))
    job.created_count = counts.get("created", 0)
    job.updated_count = counts.get("updated", 0)
    job.skipped_count = counts.get("skipped", 0)
    job.failed_count = counts.get("failed", 0)
    job.pending_count = counts.get("deferred", 0)
    job.processed_rows = sum(v for key, v in counts.items() if key != "pending")
    job.save(update_fields=["created_count", "updated_count", "skipped_count", "failed_count", "pending_count", "processed_rows"])


def check_control(job):
    job.refresh_from_db(fields=["pause_requested", "cancel_requested"])
    if job.cancel_requested:
        job.state = "cancelled"
        job.finished_at = timezone.now()
        job.save(update_fields=["state", "finished_at"])
        return True
    if job.pause_requested:
        job.state = "paused"
        job.save(update_fields=["state"])
        return True
    return False


def validate_job(job):
    job.phase = "validation"
    job.started_at = timezone.now()
    job.processed_rows = 0
    job.error_message = ""
    job.save(update_fields=["phase", "started_at", "processed_rows", "error_message"])
    job.issues.all().delete()
    job.rows.update(validation_status="unvalidated", import_status="pending", mapped={}, action="")
    seen = {}
    code_source = next((source for source, target in job.mapping.items() if target == "code"), None)
    code_counts = Counter(normalize(row.original.get(code_source)) for row in job.rows.only("original").iterator(chunk_size=200)) if code_source else Counter()
    batch = []
    processed = 0
    for row in job.rows.order_by("source_row").iterator(chunk_size=100):
        row.job = job
        mapped, action, status, issues = validate_row(row, seen, code_counts)
        row.mapped, row.action, row.validation_status = mapped, action, status
        batch.append(row)
        ImportIssue.objects.bulk_create(issues)
        processed += 1
        if len(batch) == 10:
            ImportRow.objects.bulk_update(batch, ["mapped", "action", "validation_status"])
            batch.clear()
            job.processed_rows = processed
            job.lease_until = timezone.now() + timedelta(minutes=2)
            job.save(update_fields=["processed_rows", "lease_until"])
            if check_control(job):
                return
    if batch:
        ImportRow.objects.bulk_update(batch, ["mapped", "action", "validation_status"])
    job.processed_rows = processed
    inverse = {target: source for source, target in job.mapping.items() if target}
    for resolution in job.resolutions.all():
        source = inverse.get(resolution.field)
        parent_source = inverse.get(PARENT_FIELDS.get(resolution.field))
        count = sum(1 for row in job.rows.all().iterator(chunk_size=200)
                    if normalize(row.original.get(source)) == resolution.normalized and
                    (not parent_source or normalize(row.original.get(parent_source)) == resolution.parent_value))
        resolution.affected_count = count
        resolution.save(update_fields=["affected_count"])
    job.state = "validated"
    job.validation_stale = False
    job.finished_at = timezone.now()
    job.save(update_fields=["processed_rows", "state", "validation_stale", "finished_at"])


def execute_job(job):
    job.phase = "import"
    job.started_at = timezone.now()
    job.save(update_fields=["phase", "started_at"])
    create_approved_references(job)
    for row in job.rows.order_by("source_row").iterator(chunk_size=100):
        if row.import_status != "pending":
            continue
        row.job = job
        if row.validation_status == "pending_reference":
            row.import_status = "deferred"
            row.save(update_fields=["import_status"])
        elif row.validation_status not in {"valid", "valid_warnings"} or (row.validation_status == "valid_warnings" and not job.config.get("include_warnings", True)):
            row.import_status = "skipped"
            row.save(update_fields=["import_status"])
        else:
            try:
                import_row(row)
            except Exception as exc:
                row.import_status = "failed"
                row.save(update_fields=["import_status"])
                ImportIssue.objects.create(job=job, row=row, field="", original_value="", code="execution_failed",
                                           severity="error", message=str(exc), suggestion="Correct the record and retry.")
        recount(job)
        job.lease_until = timezone.now() + timedelta(minutes=2)
        job.save(update_fields=["lease_until"])
        if check_control(job):
            return
    recount(job)
    job.warning_count = job.rows.filter(validation_status="valid_warnings", import_status__in=["created", "updated"]).count()
    job.state = "completed_errors" if job.failed_count or job.skipped_count or job.pending_count else "completed"
    job.finished_at = timezone.now()
    job.save(update_fields=["warning_count", "state", "finished_at"])


def run_one():
    now = timezone.now()
    job = ImportJob.objects.filter(
        Q(state__in=["queued_validation", "queued_import"]) |
        Q(state__in=["validating", "importing"], lease_until__lt=now)
    ).order_by("created_at").first()
    if not job:
        return False
    old_state = job.state
    phase = "validation" if old_state in {"queued_validation", "validating"} else "import"
    claim = ImportJob.objects.filter(pk=job.pk, state=old_state)
    if old_state in {"validating", "importing"}:
        claim = claim.filter(lease_until__lt=now)
    updated = claim.update(
        state="validating" if phase == "validation" else "importing",
        lease_until=now + timedelta(minutes=2),
    )
    if not updated:
        return True
    job.refresh_from_db()
    try:
        validate_job(job) if phase == "validation" else execute_job(job)
    except Exception as exc:
        job.state = "failed"
        job.error_message = str(exc)
        job.finished_at = timezone.now()
        job.save(update_fields=["state", "error_message", "finished_at"])
    return True


class Command(BaseCommand):
    help = "Run the single local background validation/import worker."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Process one queued job then exit (for tests and demos).")

    def handle(self, *args, **options):
        if options["once"]:
            run_one()
            return
        self.stdout.write("Import worker is running. Press Ctrl+C to stop.")
        try:
            while True:
                if not run_one():
                    time.sleep(1)
        except KeyboardInterrupt:
            self.stdout.write("Import worker stopped.")
