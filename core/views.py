import csv
import hashlib
import shutil
from pathlib import Path
from django.conf import settings
from django.contrib import messages
from django.core.files import File
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from .engine import effective_parent
from .models import Facility, ImportAuditEvent, ImportJob, ImportMappingTemplate, ImportReferenceResolution, ImportRow, ReferenceValue, ServiceItem
from .parsing import UploadError, checksum, stage_file
from .schema import PARENT_FIELDS, REFERENCE_FIELDS, REQUIRED_FIELDS, SOURCE_TO_TARGET, TARGET_FIELDS, normalize, suggested_mapping

SAMPLE_FILE = Path(__file__).resolve().parent.parent / "X4Nphies_Service_Item_Import_Codex_Package" / "sources" / "Untitled spreadsheet - Sheet1.csv"
MIXED_FILE = Path(__file__).resolve().parent.parent / "demo_data" / "mixed_validity.csv"


def facility_for(request):
    return Facility.objects.filter(pk=request.session.get("facility_id")).first() or Facility.objects.first()


def job_for(request, pk):
    return get_object_or_404(ImportJob, pk=pk, facility=facility_for(request))


def has_source_dates(job):
    source = next((header for header, target in job.mapping.items() if target == "discontinued_date"), None)
    return bool(source and any(row.original.get(source) for row in job.rows.only("original").iterator()))


def audit(job, action, detail=""):
    ImportAuditEvent.objects.create(job=job, action=action, detail=detail)


def dashboard(request):
    facility = facility_for(request)
    jobs = ImportJob.objects.filter(facility=facility) if facility else ImportJob.objects.none()
    return render(request, "core/dashboard.html", {"items_count": ServiceItem.objects.filter(facility=facility).count() if facility else 0,
        "job_count": jobs.count(), "success_count": jobs.filter(state="completed").count(),
        "error_count": jobs.filter(state="completed_errors").count(),
        "pending_count": ImportReferenceResolution.objects.filter(job__in=jobs, decision="").count(),
        "recent_jobs": jobs[:6]})


def items(request):
    queryset = ServiceItem.objects.filter(facility=facility_for(request)).select_related("chapter", "block")
    for field, key in [("code", "code"), ("hospital_code", "hospital_code"), ("short_description", "description")]:
        if request.GET.get(key):
            queryset = queryset.filter(**{f"{field}__icontains": request.GET[key].strip()})
    if request.GET.get("status") in {"Active", "Inactive"}:
        queryset = queryset.filter(status=request.GET["status"])
    if request.GET.get("is_package") in {"yes", "no"}:
        queryset = queryset.filter(is_package=request.GET["is_package"] == "yes")
    page = Paginator(queryset, 20).get_page(request.GET.get("page"))
    return render(request, "core/items.html", {"page": page, "total": queryset.count()})


def item_detail(request, pk):
    item = get_object_or_404(ServiceItem, pk=pk, facility=facility_for(request))
    if request.method == "POST":
        item.short_description = request.POST.get("short_description", "").strip()
        item.long_description = request.POST.get("long_description", "").strip()
        item.hospital_code = request.POST.get("hospital_code", "").strip()
        item.hospital_description = request.POST.get("hospital_description", "").strip()
        item.alias = request.POST.get("alias", "").strip()
        item.status = request.POST.get("status") if request.POST.get("status") in {"Active", "Inactive"} else item.status
        item.save()
        messages.success(request, "Service Item changes saved.")
        return redirect("item_detail", pk=item.pk)
    return render(request, "core/item_detail.html", {"item": item})


def safe_csv(value):
    text = "" if value is None else str(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else text


def csv_response(filename, headers, rows):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([safe_csv(value) for value in row])
    return response


def export_items(request):
    queryset = ServiceItem.objects.filter(facility=facility_for(request)).select_related(*REFERENCE_FIELDS)
    headers = ["Code", "ShortDescription", "LongDescription", "HospitalCode", "Status", "IsPackage", "Chapter", "Block"]
    rows = ([i.code, i.short_description, i.long_description, i.hospital_code, i.status, i.is_package,
             i.chapter.label if i.chapter else "", i.block.label if i.block else ""] for i in queryset.iterator())
    return csv_response("service_items.csv", headers, rows)


def download_sample(request):
    with SAMPLE_FILE.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.reader(source)
        rows = [next(reader), next(reader)]
    return csv_response("service_item_import_sample.csv", rows[0], [rows[1]])


@require_POST
def select_facility(request):
    facility = get_object_or_404(Facility, pk=request.POST.get("facility_id"))
    request.session["facility_id"] = facility.pk
    return redirect("dashboard")


def import_new(request):
    parent = None
    parent_id = request.POST.get("parent_job") or request.GET.get("retry")
    if parent_id:
        parent = ImportJob.objects.filter(pk=parent_id, facility=facility_for(request)).first()
    if request.method == "POST":
        upload = request.FILES.get("source_file")
        if not upload:
            messages.error(request, "Choose a CSV or XLSX file.")
        elif Path(upload.name).suffix.lower() not in {".csv", ".xlsx"}:
            messages.error(request, "Choose a CSV or XLSX file.")
        elif upload.size > 30 * 1024 * 1024:
            messages.error(request, "The prototype accepts files up to 30 MB.")
        else:
            job = ImportJob(facility=facility_for(request), filename=Path(upload.name).name,
                            file_size=upload.size, checksum=checksum(upload), parent_job=parent)
            job.source_file.save(Path(upload.name).name, upload, save=True)
            try:
                headers, count = stage_file(job)
            except UploadError as exc:
                job.source_file.delete(save=False)
                job.delete()
                messages.error(request, str(exc))
            else:
                job.mapping = parent.mapping if parent and set(parent.source_headers) == set(headers) else suggested_mapping(headers)
                job.config = parent.config if parent else {"mode": "upsert", "blank_update": "preserve", "active_discontinued_warning": True}
                job.save(update_fields=["mapping", "config"])
                audit(job, "upload", f"{count} rows staged; checksum {job.checksum}")
                messages.success(request, f"Uploaded {count} source records. No Service Items were changed.")
                return redirect("import_job", pk=job.pk)
    return render(request, "core/upload.html", {"parent": parent})


def import_job(request, pk):
    job = job_for(request, pk)
    if job.state == "validated":
        return redirect("issues", pk=pk)
    if job.state in {"queued_validation", "validating", "queued_import", "importing", "paused"}:
        return render(request, "core/progress.html", {"job": job})
    if job.state in {"completed", "completed_errors", "cancelled", "failed"}:
        return render(request, "core/results.html", {"job": job, "rows": job.rows.select_related("destination")[:20],
            "issues": job.issues.exclude(severity="warning").select_related("row")[:20],
            "duration_seconds": round((job.finished_at - job.started_at).total_seconds(), 1) if job.finished_at and job.started_at else None})
    page = Paginator(job.rows.all(), 10).get_page(request.GET.get("page"))
    return render(request, "core/preview.html", {"job": job, "page": page})


def mapping(request, pk):
    job = job_for(request, pk)
    if job.state != "mapping":
        messages.error(request, "Mapping can be changed before Test Import. Create a new job to change a validated import.")
        return redirect("import_job", pk=pk)
    if request.method == "POST":
        if request.POST.get("load_template"):
            template = ImportMappingTemplate.objects.filter(pk=request.POST.get("load_template")).first()
            if template and set(template.mapping) == set(job.source_headers):
                job.mapping = template.mapping
                job.save(update_fields=["mapping"])
                messages.success(request, f"Loaded mapping template {template.name}.")
            else:
                messages.error(request, "That template does not match this file's headers.")
            return redirect("mapping", pk=pk)
        mapping_values = {header: request.POST.get(f"map_{index}", "") for index, header in enumerate(job.source_headers)}
        transforms = {header: request.POST.get(f"transform_{index}", "trim") for index, header in enumerate(job.source_headers)}
        selected = [value for value in mapping_values.values() if value]
        if len(selected) != len(set(selected)) or not set(REQUIRED_FIELDS).issubset(selected):
            messages.error(request, "Map Code exactly once and do not map two columns to the same target field.")
        elif any(value not in TARGET_FIELDS for value in selected):
            messages.error(request, "A target field is not supported.")
        elif any(value not in {"trim", "keep", "upper", "lower"} for value in transforms.values()):
            messages.error(request, "Choose a supported text transformation.")
        else:
            job.mapping = mapping_values
            job.config = {**job.config, "transforms": transforms}
            job.save(update_fields=["mapping", "config"])
            name = request.POST.get("template_name", "").strip()
            if name:
                ImportMappingTemplate.objects.update_or_create(name=name[:100], defaults={"mapping": mapping_values})
            audit(job, "mapping_saved", name)
            messages.success(request, "Field mapping saved.")
            return redirect("configure", pk=pk)
    examples = job.rows.first().original if job.rows.exists() else {}
    mapping_rows = [(header, examples.get(header, ""), job.mapping.get(header, ""), SOURCE_TO_TARGET.get(header, ""),
                     job.config.get("transforms", {}).get(header, "trim")) for header in job.source_headers]
    return render(request, "core/mapping.html", {"job": job, "mapping_rows": mapping_rows,
        "targets": TARGET_FIELDS, "templates": ImportMappingTemplate.objects.all()})


def configure(request, pk):
    job = job_for(request, pk)
    if job.state != "mapping":
        return redirect("import_job", pk=pk)
    if request.method == "POST":
        mode = request.POST.get("mode")
        blank_update = request.POST.get("blank_update")
        date_format = request.POST.get("date_format")
        if mode not in {"create", "update", "upsert", "skip_existing"} or blank_update not in {"preserve", "clear", "default"}:
            messages.error(request, "Select a valid import mode and blank-value policy.")
        elif has_source_dates(job) and date_format not in {"dmy", "mdy", "ymd"}:
            messages.error(request, "Choose how to interpret the source dates before Test Import.")
        else:
            defaults = {}
            for field in TARGET_FIELDS:
                value = request.POST.get(f"default_{field}", "").strip()
                if value:
                    defaults[field] = value
            job.config = {**job.config, "mode": mode, "blank_update": blank_update, "date_format": date_format,
                "defaults": defaults, "strict": request.POST.get("strict") == "on",
                "active_discontinued_warning": request.POST.get("date_warning") == "on",
                "source_duplicate": request.POST.get("source_duplicate", "first") if request.POST.get("source_duplicate", "first") in {"first", "reject_all"} else "first",
                "include_warnings": request.POST.get("include_warnings") == "on", "configured": True}
            job.save(update_fields=["config"])
            audit(job, "configuration_saved", str(job.config))
            messages.success(request, "Configuration saved. You can now run Test Import.")
            return redirect("import_job", pk=pk)
    return render(request, "core/configure.html", {"job": job})


@require_POST
def start_validation(request, pk):
    job = job_for(request, pk)
    if job.state not in {"mapping", "validated"}:
        raise Http404
    if not job.mapping or "code" not in job.mapping.values() or not job.config.get("configured") or (has_source_dates(job) and job.config.get("date_format") not in {"dmy", "mdy", "ymd"}):
        messages.error(request, "Save a field mapping and import configuration first.")
        return redirect("mapping", pk=pk)
    job.state = "queued_validation"
    job.phase = "validation"
    job.pause_requested = job.cancel_requested = False
    job.save(update_fields=["state", "phase", "pause_requested", "cancel_requested"])
    audit(job, "validation_queued")
    return redirect("import_job", pk=pk)


def issues(request, pk):
    job = job_for(request, pk)
    if job.state not in {"validated", "completed", "completed_errors"}:
        return redirect("import_job", pk=pk)
    counts = dict(job.rows.values_list("validation_status").annotate(n=Count("id")))
    status = request.GET.get("status", "")
    rows = job.rows.all().prefetch_related("issues")
    if status:
        rows = rows.filter(validation_status=status)
    page = Paginator(rows, 20).get_page(request.GET.get("page"))
    return render(request, "core/issues.html", {"job": job, "counts": counts, "page": page, "filter_status": status,
        "issue_count": job.issues.count(), "missing_count": job.resolutions.filter(affected_count__gt=0).count()})


def resolve_references(request, pk):
    job = job_for(request, pk)
    if job.state != "validated":
        return redirect("import_job", pk=pk)
    if request.method == "POST":
        resolution = get_object_or_404(ImportReferenceResolution, pk=request.POST.get("resolution_id"), job=job)
        decision = request.POST.get("decision")
        candidate = None
        if decision == "map":
            candidate = ReferenceValue.objects.filter(pk=request.POST.get("reference_id"), kind=REFERENCE_FIELDS[resolution.field], active=True).first()
            if candidate and resolution.field in PARENT_FIELDS:
                parent = effective_parent(job, PARENT_FIELDS[resolution.field], resolution.parent_value)
                valid_parent = candidate.parent_id == parent.pk if parent else normalize(candidate.parent.label if candidate.parent else "") == resolution.parent_value
                if not valid_parent:
                    candidate = None
            if not candidate:
                messages.error(request, "Choose an active reference with the correct parent.")
                return redirect("resolve_references", pk=pk)
        if decision == "create" and request.POST.get("approve_create") != "on":
            messages.error(request, "Tick the approval box to create a new demo reference during import.")
            return redirect("resolve_references", pk=pk)
        if decision not in {"map", "create", "blank", "skip", "defer"}:
            messages.error(request, "Choose a reference decision.")
            return redirect("resolve_references", pk=pk)
        if decision == "blank" and resolution.field == "chapter":
            messages.error(request, "Chapter cannot be left empty for a populated source value.")
            return redirect("resolve_references", pk=pk)
        resolution.decision = decision
        resolution.resolved_reference = candidate
        resolution.approved = decision == "create"
        resolution.save(update_fields=["decision", "resolved_reference", "approved", "updated_at"])
        job.validation_stale = True
        job.save(update_fields=["validation_stale"])
        audit(job, "reference_decision", f"{resolution.field}: {resolution.source_value} → {decision}")
        messages.success(request, "Decision saved. Retest to refresh record eligibility.")
        return redirect("resolve_references", pk=pk)
    grouped = []
    for resolution in job.resolutions.filter(affected_count__gt=0):
        candidates = ReferenceValue.objects.filter(kind=REFERENCE_FIELDS[resolution.field], active=True)
        if resolution.field in PARENT_FIELDS:
            parent = effective_parent(job, PARENT_FIELDS[resolution.field], resolution.parent_value)
            candidates = candidates.filter(parent=parent) if parent else candidates.filter(parent__normalized=resolution.parent_value)
        else:
            candidates = candidates.filter(parent__isnull=True)
        grouped.append((resolution, candidates))
    return render(request, "core/references_resolve.html", {"job": job, "grouped": grouped})


def confirm_import(request, pk):
    job = job_for(request, pk)
    if job.state != "validated":
        return redirect("import_job", pk=pk)
    if job.validation_stale:
        messages.error(request, "Reference decisions changed. Run Test Import again before confirming.")
        return redirect("issues", pk=pk)
    counts = dict(job.rows.values_list("validation_status").annotate(n=Count("id")))
    blocked = counts.get("invalid", 0) + counts.get("duplicate", 0) + counts.get("pending_reference", 0)
    if request.method == "POST":
        if job.config.get("strict") and blocked:
            messages.error(request, "Strict mode requires every blocking issue to be resolved first.")
        elif request.POST.get("confirm") != "yes":
            messages.error(request, "Confirm the reviewed import plan.")
        else:
            job.plan = {"counts": counts, "mapping": job.mapping, "config": job.config,
                        "approved_references": list(job.resolutions.filter(decision="create", approved=True).values_list("id", flat=True))}
            job.state = "queued_import"
            job.phase = "import"
            job.processed_rows = 0
            job.save(update_fields=["plan", "state", "phase", "processed_rows"])
            audit(job, "import_confirmed", str(job.plan))
            return redirect("import_job", pk=pk)
    eligible_statuses = ["valid", "valid_warnings"] if job.config.get("include_warnings", True) else ["valid"]
    return render(request, "core/confirm.html", {"job": job, "counts": counts, "blocked": blocked,
        "eligible_create": job.rows.filter(validation_status__in=eligible_statuses, action="create").count(),
        "eligible_update": job.rows.filter(validation_status__in=eligible_statuses, action="update").count(),
        "approved": job.resolutions.filter(decision="create", approved=True)})


def progress(request, pk):
    job = job_for(request, pk)
    return JsonResponse({"state": job.state, "phase": job.phase, "total": job.total_rows,
        "processed": job.processed_rows, "percent": job.percent, "created": job.created_count,
        "updated": job.updated_count, "skipped": job.skipped_count, "failed": job.failed_count,
        "pending": job.pending_count, "error": job.error_message,
        "elapsed_seconds": round((timezone.now() - job.started_at).total_seconds(), 1) if job.started_at else 0,
        "recent_errors": list(job.issues.exclude(severity="warning").order_by("-id").values_list("message", flat=True)[:3])})


@require_POST
def control_job(request, pk):
    job = job_for(request, pk)
    action = request.POST.get("action")
    if action == "pause" and job.state in {"queued_validation", "validating", "queued_import", "importing"}:
        if job.state.startswith("queued_"):
            job.state = "paused"
            job.save(update_fields=["state"])
        else:
            job.pause_requested = True
            job.save(update_fields=["pause_requested"])
    elif action == "cancel" and job.state in {"queued_validation", "validating", "queued_import", "importing", "paused"}:
        if job.state == "paused" or job.state.startswith("queued_"):
            job.state = "cancelled"
            job.finished_at = timezone.now()
            job.save(update_fields=["state", "finished_at"])
        else:
            job.cancel_requested = True
            job.save(update_fields=["cancel_requested"])
    elif action == "resume" and job.state == "paused":
        job.pause_requested = False
        job.state = "queued_validation" if job.phase == "validation" else "queued_import"
        job.save(update_fields=["pause_requested", "state"])
    else:
        messages.error(request, "This control is unavailable for the current job state.")
        return redirect("import_job", pk=pk)
    audit(job, f"job_{action}")
    return redirect("import_job", pk=pk)


def report(request, pk, kind):
    job = job_for(request, pk)
    if kind == "summary":
        headers = ["Job ID", "Filename", "Total", "Created", "Updated", "Total Successful", "Imported with Warnings", "Skipped", "Failed", "Deferred", "Not Processed", "Status"]
        rows = [[job.pk, job.filename, job.total_rows, job.created_count, job.updated_count,
                 job.created_count + job.updated_count, job.warning_count, job.skipped_count,
                 job.failed_count, job.pending_count, job.unprocessed_count, job.get_state_display()]]
    elif kind == "errors":
        headers = ["Source Row", "Code", "ShortDescription", "Field", "Original Value", "Error Type", "Severity", "Message", "Suggested Correction", "Final Status", "Retry Eligibility"]
        rows = ([i.row.source_row if i.row else "", i.row.original.get("Code", "") if i.row else "",
                 i.row.original.get("ShortDescription", "") if i.row else "", i.field, i.original_value,
                 i.code, i.severity, i.message, i.suggestion, i.row.import_status if i.row else "",
                 "Correct and reupload" if i.row and i.row.import_status not in {"created", "updated"} else "No"]
                for i in job.issues.select_related("row").iterator())
    elif kind == "failed":
        headers = job.source_headers
        rows = ([row.original.get(header, "") for header in headers] for row in job.rows.exclude(import_status__in=["created", "updated"]).iterator())
    else:
        raise Http404
    return csv_response(f"import_{job.pk}_{kind}.csv", headers, rows)


def history(request):
    jobs = ImportJob.objects.filter(facility=facility_for(request))
    page = Paginator(jobs, 20).get_page(request.GET.get("page"))
    return render(request, "core/history.html", {"page": page})


def references(request):
    if request.method == "POST":
        if request.POST.get("action") == "toggle":
            ref = get_object_or_404(ReferenceValue, pk=request.POST.get("reference_id"))
            ref.active = not ref.active
            ref.save(update_fields=["active"])
            messages.success(request, f"{ref.label} is now {'active' if ref.active else 'inactive'}.")
            return redirect("references")
        kind = request.POST.get("kind")
        label = request.POST.get("label", "").strip()
        parent = ReferenceValue.objects.filter(pk=request.POST.get("parent_id")).first() if request.POST.get("parent_id") else None
        parent_kind = {"block": "chapter", "sub_cost_center": "cost_center", "sub_department": "department"}.get(kind)
        if kind not in REFERENCE_FIELDS.values() or not label:
            messages.error(request, "Choose a reference type and enter a label.")
        elif parent_kind and (not parent or parent.kind != parent_kind):
            messages.error(request, f"{kind.replace('_', ' ').title()} needs a {parent_kind.replace('_', ' ').title()} parent.")
        elif not parent_kind and parent:
            messages.error(request, "This reference type does not use a parent.")
        else:
            _, created = ReferenceValue.objects.get_or_create(kind=kind, normalized=normalize(label), parent=parent,
                defaults={"label": label, "is_demo": True})
            messages.success(request, "Demo reference created." if created else "That reference already exists.")
        return redirect("references")
    kind = request.GET.get("kind", "")
    queryset = ReferenceValue.objects.select_related("parent")
    if kind:
        queryset = queryset.filter(kind=kind)
    page = Paginator(queryset, 25).get_page(request.GET.get("page"))
    return render(request, "core/references.html", {"page": page, "kinds": sorted(set(REFERENCE_FIELDS.values())),
        "parents": ReferenceValue.objects.filter(kind__in=["chapter", "cost_center", "department"])})


def demo(request):
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "seed":
            from django.core.management import call_command
            call_command("seed_demo")
            messages.success(request, "Deterministic demo references are ready.")
        elif action in {"load_sample", "load_mixed"}:
            from django.core.files import File
            selected = SAMPLE_FILE if action == "load_sample" else MIXED_FILE
            with selected.open("rb") as source:
                job = ImportJob(facility=facility_for(request), filename=selected.name,
                    file_size=selected.stat().st_size, checksum=hashlib.sha256(source.read()).hexdigest())
                source.seek(0)
                job.source_file.save(selected.name, File(source), save=True)
            stage_file(job)
            job.mapping = suggested_mapping(job.source_headers)
            job.config = {"mode": "upsert", "blank_update": "preserve", "active_discontinued_warning": True}
            job.save(update_fields=["mapping", "config"])
            audit(job, "sample_loaded")
            messages.success(request, "The chosen demo CSV is staged as a new job.")
            return redirect("import_job", pk=job.pk)
        elif action == "reset" and request.POST.get("confirmation") == "RESET DEMO":
            for job in ImportJob.objects.all():
                job.source_file.delete(save=False)
            ImportJob.objects.all().delete()
            ServiceItem.objects.all().delete()
            ReferenceValue.objects.filter(parent__isnull=False).delete()
            ReferenceValue.objects.all().delete()
            shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)
            Path(settings.MEDIA_ROOT).mkdir(parents=True, exist_ok=True)
            from django.core.management import call_command
            call_command("seed_demo")
            messages.success(request, "Demo jobs and items were deleted; reference fixtures were reseeded.")
        else:
            messages.error(request, "Type RESET DEMO to confirm the reset.")
        return redirect("demo")
    return render(request, "core/demo.html", {"source_name": SAMPLE_FILE.name, "mixed_name": MIXED_FILE.name,
        "item_count": ServiceItem.objects.count(), "job_count": ImportJob.objects.count(), "reference_count": ReferenceValue.objects.count()})
