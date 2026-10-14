from django.db import models
from django.db.models import Q


class Facility(models.Model):
    name = models.CharField(max_length=180, unique=True)
    code = models.CharField(max_length=40, unique=True)

    def __str__(self):
        return self.name


class ReferenceValue(models.Model):
    kind = models.CharField(max_length=40, db_index=True)
    label = models.CharField(max_length=180)
    normalized = models.CharField(max_length=180)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="children")
    active = models.BooleanField(default=True)
    is_demo = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["kind", "normalized", "parent"], name="unique_reference_with_parent"),
                       models.UniqueConstraint(fields=["kind", "normalized"], condition=Q(parent__isnull=True), name="unique_root_reference")]
        ordering = ["kind", "label"]

    def __str__(self):
        return f"{self.kind}: {self.label}"


class ServiceItem(models.Model):
    facility = models.ForeignKey(Facility, on_delete=models.PROTECT)
    code = models.CharField(max_length=100)
    short_description = models.CharField(max_length=500, blank=True)
    long_description = models.TextField(blank=True)
    hospital_code = models.CharField(max_length=100, blank=True)
    hospital_description = models.TextField(blank=True)
    is_listed = models.BooleanField(null=True, blank=True)
    is_package = models.BooleanField(null=True, blank=True)
    alias = models.CharField(max_length=255, blank=True)
    chapter = models.ForeignKey(ReferenceValue, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    block = models.ForeignKey(ReferenceValue, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    cost_center = models.ForeignKey(ReferenceValue, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    sub_cost_center = models.ForeignKey(ReferenceValue, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    department = models.ForeignKey(ReferenceValue, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    sub_department = models.ForeignKey(ReferenceValue, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    category = models.ForeignKey(ReferenceValue, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    tax_category = models.ForeignKey(ReferenceValue, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    service_type = models.ForeignKey(ReferenceValue, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    material_cost = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    registration_number = models.CharField(max_length=100, blank=True)
    scientific_name = models.CharField(max_length=500, blank=True)
    scientific_code = models.CharField(max_length=100, blank=True)
    description_code = models.CharField(max_length=100, blank=True)
    strength = models.CharField(max_length=100, blank=True)
    strength_unit = models.ForeignKey(ReferenceValue, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    pharmaceutical_form = models.ForeignKey(ReferenceValue, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    administration_route = models.ForeignKey(ReferenceValue, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    package_type = models.ForeignKey(ReferenceValue, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    package_size = models.CharField(max_length=100, blank=True)
    product_control = models.ForeignKey(ReferenceValue, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    distribution_area = models.ForeignKey(ReferenceValue, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    discontinued_date = models.DateField(null=True, blank=True)
    public_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=20, default="Active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["facility", "code"], name="unique_facility_service_code")]
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} — {self.short_description}"


class ImportJob(models.Model):
    STATES = [("mapping", "Mapping"), ("queued_validation", "Queued for Test Import"),
              ("validating", "Validating"), ("validated", "Test Import complete"),
              ("queued_import", "Queued for import"), ("importing", "Importing"),
              ("paused", "Paused"), ("completed", "Completed Successfully"),
              ("completed_errors", "Completed with Errors"), ("failed", "Failed"),
              ("cancelled", "Cancelled")]
    facility = models.ForeignKey(Facility, on_delete=models.PROTECT)
    parent_job = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL)
    filename = models.CharField(max_length=255)
    source_file = models.FileField(upload_to="imports/%Y/%m/%d/")
    checksum = models.CharField(max_length=64)
    file_size = models.PositiveBigIntegerField(default=0)
    source_headers = models.JSONField(default=list)
    mapping = models.JSONField(default=dict)
    config = models.JSONField(default=dict)
    plan = models.JSONField(default=dict)
    validation_stale = models.BooleanField(default=False)
    state = models.CharField(max_length=30, choices=STATES, default="mapping", db_index=True)
    phase = models.CharField(max_length=20, blank=True)
    pause_requested = models.BooleanField(default=False)
    cancel_requested = models.BooleanField(default=False)
    lease_until = models.DateTimeField(null=True, blank=True)
    total_rows = models.PositiveIntegerField(default=0)
    processed_rows = models.PositiveIntegerField(default=0)
    created_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    pending_count = models.PositiveIntegerField(default=0)
    warning_count = models.PositiveIntegerField(default=0)
    submitted_by = models.CharField(max_length=100, default="Demo User")
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def percent(self):
        return round(self.processed_rows * 100 / self.total_rows) if self.total_rows else 0

    @property
    def unprocessed_count(self):
        return max(self.total_rows - self.processed_rows, 0)


class ImportRow(models.Model):
    job = models.ForeignKey(ImportJob, on_delete=models.CASCADE, related_name="rows")
    source_row = models.PositiveIntegerField()
    original = models.JSONField(default=dict)
    mapped = models.JSONField(default=dict)
    validation_status = models.CharField(max_length=30, default="unvalidated", db_index=True)
    action = models.CharField(max_length=20, blank=True)
    import_status = models.CharField(max_length=30, default="pending", db_index=True)
    destination = models.ForeignKey(ServiceItem, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["job", "source_row"], name="unique_job_source_row")]
        ordering = ["source_row"]


class ImportIssue(models.Model):
    job = models.ForeignKey(ImportJob, on_delete=models.CASCADE, related_name="issues")
    row = models.ForeignKey(ImportRow, null=True, blank=True, on_delete=models.CASCADE, related_name="issues")
    field = models.CharField(max_length=100, blank=True)
    original_value = models.TextField(blank=True)
    code = models.CharField(max_length=60)
    severity = models.CharField(max_length=20, choices=[("error", "Error"), ("warning", "Warning"), ("reference", "Reference")])
    message = models.TextField()
    suggestion = models.TextField(blank=True)

    class Meta:
        ordering = ["row__source_row", "id"]


class ImportReferenceResolution(models.Model):
    job = models.ForeignKey(ImportJob, on_delete=models.CASCADE, related_name="resolutions")
    field = models.CharField(max_length=60)
    source_value = models.CharField(max_length=180)
    normalized = models.CharField(max_length=180)
    parent_value = models.CharField(max_length=180, blank=True)
    decision = models.CharField(max_length=20, blank=True)
    resolved_reference = models.ForeignKey(ReferenceValue, null=True, blank=True, on_delete=models.SET_NULL)
    approved = models.BooleanField(default=False)
    affected_count = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["job", "field", "normalized", "parent_value"], name="unique_job_missing_reference")]
        ordering = ["field", "source_value"]


class ImportMappingTemplate(models.Model):
    name = models.CharField(max_length=100, unique=True)
    mapping = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class ImportAuditEvent(models.Model):
    job = models.ForeignKey(ImportJob, null=True, blank=True, on_delete=models.CASCADE)
    action = models.CharField(max_length=100)
    detail = models.TextField(blank=True)
    actor = models.CharField(max_length=100, default="Demo User")
    created_at = models.DateTimeField(auto_now_add=True)
