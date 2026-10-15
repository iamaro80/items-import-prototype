import csv
import io
import tempfile
from pathlib import Path
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from openpyxl import Workbook
from .management.commands.run_import_worker import run_one
from .models import Facility, ImportAuditEvent, ImportJob, ImportMappingTemplate, ReferenceValue, ServiceItem
from .schema import SOURCE_TO_TARGET
from .views import MIXED_FILE, SAMPLE_FILE, safe_csv


class ImportWorkflowTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.media_override = override_settings(MEDIA_ROOT=self.media_dir.name)
        self.media_override.enable()
        call_command("seed_demo", verbosity=0)
        self.facility = Facility.objects.get(code="KAMC-AH-DEMO")

    def tearDown(self):
        self.media_override.disable()
        self.media_dir.cleanup()

    def upload(self, path, parent=None):
        data = {"source_file": SimpleUploadedFile(path.name, path.read_bytes(), content_type="text/csv")}
        if parent:
            data["parent_job"] = str(parent.pk)
        response = self.client.post("/import/new/", data)
        self.assertEqual(response.status_code, 302)
        job = ImportJob.objects.latest("pk")
        self.assertEqual(job.total_rows, 49 if path == SAMPLE_FILE else 7)
        self.assertEqual(len(job.source_headers), 33)
        return job

    def configure(self, job, mode="upsert", date_format="dmy"):
        mapping = {f"map_{index}": job.mapping[header] for index, header in enumerate(job.source_headers)}
        response = self.client.post(f"/import/{job.pk}/mapping/", mapping)
        self.assertEqual(response.status_code, 302)
        response = self.client.post(f"/import/{job.pk}/configure/", {
            "mode": mode, "blank_update": "preserve", "date_format": date_format, "date_warning": "on", "include_warnings": "on",
        })
        self.assertEqual(response.status_code, 302)
        job.refresh_from_db()
        return job

    def validate(self, job):
        self.assertEqual(self.client.post(f"/import/{job.pk}/validate/").status_code, 302)
        self.assertTrue(run_one())
        job.refresh_from_db()
        self.assertEqual(job.state, "validated")
        return job

    def execute(self, job):
        self.assertEqual(self.client.post(f"/import/{job.pk}/confirm/", {"confirm": "yes"}).status_code, 302)
        self.assertTrue(run_one())
        job.refresh_from_db()
        return job

    def test_supplied_headers_aliases_and_dry_run(self):
        job = self.upload(SAMPLE_FILE)
        self.assertEqual(job.source_headers, list(SOURCE_TO_TARGET))
        self.assertEqual(job.rows.first().source_row, 2)
        self.assertEqual(job.mapping["LongDesription"], "long_description")
        self.assertEqual(job.mapping["IsPackge"], "is_package")
        self.assertEqual(job.mapping["SubDepatment"], "sub_department")
        self.configure(job)
        self.validate(job)
        self.assertEqual(ServiceItem.objects.count(), 0)
        self.assertEqual(job.rows.filter(validation_status="valid_warnings").count(), 47)
        self.assertEqual(job.rows.filter(validation_status="pending_reference").count(), 1)
        self.assertEqual(job.resolutions.count(), 2)
        self.assertEqual(job.issues.filter(code="active_with_discontinued_date").count(), 47)

    def test_explicit_reference_approval_and_full_import(self):
        job = self.validate(self.configure(self.upload(SAMPLE_FILE)))
        block = job.resolutions.get(field="block")
        cost = job.resolutions.get(field="cost_center")
        existing = ReferenceValue.objects.get(kind="block", label="Other", parent__label="Pharmaceuticals")
        self.client.post(f"/import/{job.pk}/references/", {"resolution_id": block.pk, "decision": "map", "reference_id": existing.pk})
        self.client.post(f"/import/{job.pk}/references/", {"resolution_id": cost.pk, "decision": "create", "approve_create": "on"})
        self.assertFalse(ReferenceValue.objects.filter(kind="cost_center", label=cost.source_value).exists())
        self.client.post(f"/import/{job.pk}/confirm/", {"confirm": "yes"})
        job.refresh_from_db()
        self.assertEqual(job.state, "validated")
        self.assertTrue(job.validation_stale)
        self.validate(job)
        self.assertEqual(job.rows.filter(validation_status="pending_reference").count(), 0)
        self.assertEqual(ServiceItem.objects.count(), 0)
        job = self.execute(job)
        self.assertEqual(job.state, "completed")
        self.assertEqual((job.created_count, job.updated_count, job.failed_count), (49, 0, 0))
        self.assertEqual(job.warning_count, 47)
        self.assertEqual(ServiceItem.objects.filter(facility=self.facility).count(), 49)
        self.assertTrue(ReferenceValue.objects.filter(kind="cost_center", label=cost.source_value).exists())

    def test_partial_success_and_corrected_retry(self):
        ServiceItem.objects.create(facility=self.facility, code="1801210419", short_description="Old description")
        job = self.execute(self.validate(self.configure(self.upload(MIXED_FILE))))
        self.assertEqual(job.state, "completed_errors")
        self.assertEqual((job.created_count, job.updated_count, job.skipped_count, job.failed_count, job.pending_count), (3, 1, 2, 0, 1))
        self.assertEqual(ServiceItem.objects.count(), 4)
        self.assertEqual(ServiceItem.objects.get(code="1801210419").short_description, "Synthetic update to an existing code")
        download = self.client.get(f"/import/{job.pk}/report/failed/")
        self.assertEqual(download.status_code, 200)
        reader = csv.DictReader(io.StringIO(download.content.decode("utf-8-sig")))
        failed = list(reader)
        self.assertEqual(len(failed), 3)
        self.assertEqual(reader.fieldnames, job.source_headers)
        for row in failed:
            if row["Code"] == "DEMO-BAD-DEC":
                row["MaterialCost"] = "25.50"
            if row["Code"] == "DEMO-MISS-REF":
                row["Block"] = "Other"
            if row["Code"] == "DEMO-DUP-001":
                row["Code"] = row["HospitalCode"] = "DEMO-DUP-FIXED"
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=reader.fieldnames)
        writer.writeheader()
        writer.writerows(failed)
        retry_file = SimpleUploadedFile("corrected.csv", output.getvalue().encode(), content_type="text/csv")
        self.assertEqual(self.client.post("/import/new/", {"source_file": retry_file, "parent_job": job.pk}).status_code, 302)
        retry = ImportJob.objects.latest("pk")
        self.assertEqual(retry.parent_job_id, job.pk)
        self.assertEqual(retry.mapping, job.mapping)
        self.assertEqual(retry.rows.count(), 3)
        self.assertEqual(self.client.post(f"/import/{retry.pk}/validate/").status_code, 302)
        run_one()
        retry.refresh_from_db()
        self.assertEqual(retry.rows.filter(validation_status__in=["valid", "valid_warnings"]).count(), 3)
        retry = self.execute(retry)
        self.assertEqual(retry.created_count, 3)
        self.assertEqual(ServiceItem.objects.count(), 7)

    def test_pause_resume_and_idempotent_worker_recovery(self):
        job = self.validate(self.configure(self.upload(MIXED_FILE)))
        self.client.post(f"/import/{job.pk}/confirm/", {"confirm": "yes"})
        job.refresh_from_db()
        job.pause_requested = True
        job.save(update_fields=["pause_requested"])
        run_one()
        job.refresh_from_db()
        self.assertEqual(job.state, "paused")
        self.assertEqual(job.created_count + job.updated_count + job.skipped_count + job.pending_count, 1)
        self.client.post(f"/import/{job.pk}/control/", {"action": "resume"})
        run_one()
        job.refresh_from_db()
        self.assertEqual(job.state, "completed_errors")
        self.assertEqual(job.created_count, 4)  # no pre-existing item in this test
        self.assertEqual(ServiceItem.objects.count(), 4)
        self.assertFalse(run_one())
        self.assertEqual(ServiceItem.objects.count(), 4)

    def test_ui_and_csv_formula_protection(self):
        for url in ["/", "/items/", "/history/", "/references/", "/demo/", "/import/new/"]:
            self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(safe_csv("=SUM(1,2)"), "'=SUM(1,2)")

    def test_ambiguous_date_requires_selection_and_strict_blocks(self):
        job = self.upload(SAMPLE_FILE)
        mapping = {f"map_{index}": job.mapping[header] for index, header in enumerate(job.source_headers)}
        self.client.post(f"/import/{job.pk}/mapping/", mapping)
        self.client.post(f"/import/{job.pk}/configure/", {
            "mode": "upsert", "blank_update": "preserve", "date_format": "", "strict": "on",
        })
        job.refresh_from_db()
        self.assertNotIn("date_format", job.config)
        self.assertEqual(self.client.post(f"/import/{job.pk}/validate/").status_code, 302)
        job.refresh_from_db()
        self.assertEqual(job.state, "mapping")
        self.client.post(f"/import/{job.pk}/configure/", {
            "mode": "upsert", "blank_update": "preserve", "date_format": "dmy", "strict": "on",
        })
        self.validate(job)
        self.client.post(f"/import/{job.pk}/confirm/", {"confirm": "yes"})
        job.refresh_from_db()
        self.assertEqual(job.state, "validated")

    def test_wrong_parent_reference_is_rejected_and_skip_retests(self):
        job = self.validate(self.configure(self.upload(SAMPLE_FILE)))
        block = job.resolutions.get(field="block")
        wrong_parent = ReferenceValue.objects.get(kind="block", label="Other", parent__label="Other Services")
        self.client.post(f"/import/{job.pk}/references/", {
            "resolution_id": block.pk, "decision": "map", "reference_id": wrong_parent.pk,
        })
        block.refresh_from_db()
        self.assertFalse(block.decision)
        self.client.post(f"/import/{job.pk}/references/", {"resolution_id": block.pk, "decision": "skip"})
        self.validate(job)
        self.assertEqual(job.rows.filter(validation_status="excluded").count(), 1)
        self.assertEqual(ServiceItem.objects.count(), 0)

    def test_malformed_csv_and_xlsx_staging(self):
        malformed = SimpleUploadedFile("bad.csv", b"Code,Code\nA,B\n", content_type="text/csv")
        response = self.client.post("/import/new/", {"source_file": malformed}, follow=True)
        self.assertContains(response, "duplicate column headers")
        self.assertEqual(ImportJob.objects.count(), 0)
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Code", "ShortDescription"])
        sheet.append(["00123", "Example item"])
        buffer = io.BytesIO()
        workbook.save(buffer)
        file = SimpleUploadedFile("sample.xlsx", buffer.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertEqual(self.client.post("/import/new/", {"source_file": file}).status_code, 302)
        job = ImportJob.objects.get()
        self.assertEqual(job.source_headers, ["Code", "ShortDescription"])
        self.assertEqual(job.rows.get().original["Code"], "00123")

    def test_duplicate_policy_and_warning_exclusion(self):
        job = self.configure(self.upload(MIXED_FILE))
        self.client.post(f"/import/{job.pk}/configure/", {
            "mode": "upsert", "blank_update": "preserve", "date_format": "dmy",
            "date_warning": "on", "source_duplicate": "reject_all",
        })
        self.validate(job)
        self.assertEqual(job.rows.filter(validation_status="duplicate").count(), 2)
        job = self.execute(job)
        self.assertEqual(job.created_count, 0)
        self.assertEqual(job.skipped_count, 6)
        self.assertEqual(job.pending_count, 1)
        self.assertEqual(ServiceItem.objects.count(), 0)

    def test_runtime_failure_isolates_one_row(self):
        job = self.validate(self.configure(self.upload(MIXED_FILE)))
        row = job.rows.get(original__Code="DEMO-NEW-001")
        mapped = row.mapped
        mapped["short_description"] = "X" * 600
        row.mapped = mapped
        row.save(update_fields=["mapped"])
        job = self.execute(job)
        self.assertEqual(job.state, "completed_errors")
        self.assertEqual(job.failed_count, 1)
        self.assertEqual(job.created_count, 3)
        self.assertEqual(ServiceItem.objects.count(), 3)
        self.assertTrue(job.issues.filter(row=row, code="execution_failed").exists())

    def test_reset_restores_first_run_state(self):
        job = self.upload(SAMPLE_FILE)
        uploaded_path = Path(job.source_file.path)
        ServiceItem.objects.create(facility=self.facility, code="RESET-TEST")
        ImportMappingTemplate.objects.create(name="Saved mapping", mapping={"Code": "code"})
        ImportAuditEvent.objects.create(action="orphaned audit")
        Facility.objects.create(code="CUSTOM", name="Custom Facility")
        ReferenceValue.objects.create(kind="category", label="Custom", normalized="custom")
        call_command("reset_demo", yes=True, verbosity=0)
        self.assertEqual(ImportJob.objects.count(), 0)
        self.assertEqual(ServiceItem.objects.count(), 0)
        self.assertEqual(ImportMappingTemplate.objects.count(), 0)
        self.assertEqual(ImportAuditEvent.objects.count(), 0)
        self.assertEqual(set(Facility.objects.values_list("code", flat=True)), {"KAMC-AH-DEMO", "UAT-DEMO"})
        self.assertEqual(ReferenceValue.objects.count(), 21)
        self.assertFalse(uploaded_path.exists())
        self.assertTrue(SAMPLE_FILE.exists())
        self.assertTrue(MIXED_FILE.exists())

    def test_demo_reset_action_restores_first_run_state(self):
        self.upload(SAMPLE_FILE)
        ImportMappingTemplate.objects.create(name="Saved mapping")
        session = self.client.session
        session["facility_id"] = self.facility.pk
        session.save()
        response = self.client.post("/demo/", {"action": "reset", "confirmation": "RESET DEMO"}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "First-run demo state restored")
        self.assertEqual(ImportJob.objects.count(), 0)
        self.assertEqual(ImportMappingTemplate.objects.count(), 0)
        self.assertNotIn("facility_id", self.client.session)

    def test_reset_rejects_an_active_import(self):
        job = self.upload(SAMPLE_FILE)
        job.state = "importing"
        job.save(update_fields=["state"])
        with self.assertRaisesMessage(CommandError, "An import is running"):
            call_command("reset_demo", yes=True, verbosity=0)
        self.assertTrue(ImportJob.objects.filter(pk=job.pk).exists())
        self.assertTrue(Path(job.source_file.path).exists())
