"""Import business rules. Keep changes here when stakeholders revise the prototype."""
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from django.db import IntegrityError, transaction
from django.db.models import Count
from .models import ImportIssue, ImportReferenceResolution, ReferenceValue, ServiceItem
from .schema import BOOLEAN_FIELDS, DECIMAL_FIELDS, PARENT_FIELDS, REFERENCE_FIELDS, REQUIRED_FIELDS, STATUS_VALUES, normalize


def issue(row, field, code, severity, message, suggestion=""):
    source = next((key for key, target in row.job.mapping.items() if target == field), None)
    return ImportIssue(job=row.job, row=row, field=field, original_value=str(row.original.get(source, "")),
                       code=code, severity=severity, message=message, suggestion=suggestion)


def _resolution(job, field, value, parent_value=""):
    return ImportReferenceResolution.objects.filter(
        job=job, field=field, normalized=normalize(value), parent_value=normalize(parent_value)
    ).first()


def _find_reference(field, value, parent_value="", parent_id=None):
    matches = ReferenceValue.objects.filter(kind=REFERENCE_FIELDS[field], normalized=normalize(value), active=True)
    if field in PARENT_FIELDS:
        matches = matches.filter(parent_id=parent_id) if parent_id else matches.filter(parent__kind=REFERENCE_FIELDS[PARENT_FIELDS[field]], parent__normalized=normalize(parent_value))
    else:
        matches = matches.filter(parent__isnull=True)
    return list(matches[:2])


def effective_parent(job, parent_field, parent_value):
    resolution = _resolution(job, parent_field, parent_value)
    if resolution and resolution.decision in {"map", "create"} and resolution.resolved_reference_id:
        return resolution.resolved_reference
    return ReferenceValue.objects.filter(kind=REFERENCE_FIELDS[parent_field], normalized=normalize(parent_value), parent__isnull=True).first()


def _parse_date(value, fmt):
    formats = {"dmy": "%d/%m/%Y %I:%M:%S %p", "mdy": "%m/%d/%Y %I:%M:%S %p",
               "ymd": "%Y-%m-%d"}
    if fmt not in formats:
        raise ValueError("Select a date format in Configure before validation.")
    if fmt == "ymd":
        return datetime.strptime(value[:10], formats[fmt]).date().isoformat()
    try:
        return datetime.strptime(value, formats[fmt]).date().isoformat()
    except ValueError:
        return datetime.strptime(value.split(" ")[0], formats[fmt].split(" ")[0]).date().isoformat()


def validate_row(row, seen_codes, source_code_counts=None):
    job = row.job
    mapped = {}
    issues = []
    config = job.config
    defaults = config.get("defaults", {})
    for source, target in job.mapping.items():
        if not target:
            continue
        raw = row.original.get(source, "")
        value = str(raw) if raw is not None else ""
        transform = config.get("transforms", {}).get(source, "trim")
        if transform == "trim":
            value = value.strip()
        elif transform == "upper":
            value = value.strip().upper()
        elif transform == "lower":
            value = value.strip().lower()
        if not value and target in defaults:
            value = str(defaults[target]).strip()
        mapped[target] = value or None
    for field in REQUIRED_FIELDS:
        if not mapped.get(field):
            issues.append(issue(row, field, "required", "error", f"{field.replace('_', ' ').title()} is required."))
    for field in BOOLEAN_FIELDS:
        value = mapped.get(field)
        if value is None:
            continue
        if normalize(value) in {"yes", "true", "1", "y"}:
            mapped[field] = True
        elif normalize(value) in {"no", "false", "0", "n"}:
            mapped[field] = False
        else:
            issues.append(issue(row, field, "invalid_boolean", "error", "Use yes/no, true/false, or 1/0."))
    for field in DECIMAL_FIELDS:
        value = mapped.get(field)
        if value is None:
            continue
        try:
            number = Decimal(str(value).replace(",", ""))
            if not number.is_finite() or number < 0:
                raise InvalidOperation
            mapped[field] = str(number)
        except (InvalidOperation, ValueError):
            issues.append(issue(row, field, "invalid_decimal", "error", "Enter a non-negative decimal value."))
    if mapped.get("discontinued_date"):
        try:
            mapped["discontinued_date"] = _parse_date(mapped["discontinued_date"], config.get("date_format"))
        except ValueError as exc:
            issues.append(issue(row, "discontinued_date", "invalid_date", "error", str(exc)))
    if mapped.get("status") and mapped["status"] not in STATUS_VALUES:
        issues.append(issue(row, "status", "invalid_status", "error", "Status must be Active or Inactive."))
    if mapped.get("status") == "Active" and mapped.get("discontinued_date") and config.get("active_discontinued_warning", True):
        issues.append(issue(row, "discontinued_date", "active_with_discontinued_date", "warning",
                            "Active item has a discontinuation date. Check the lifecycle status."))
    code = mapped.get("code")
    if code:
        key = normalize(code)
        if config.get("source_duplicate", "first") == "reject_all" and source_code_counts and source_code_counts.get(key, 0) > 1:
            issues.append(issue(row, "code", "duplicate_source", "error", "Service code appears more than once in this file."))
        elif key in seen_codes:
            issues.append(issue(row, "code", "duplicate_source", "error",
                                f"The same service code first appeared on source row {seen_codes[key]}."))
        else:
            seen_codes[key] = row.source_row
    ref_ids = {}
    resolution_actions = set()
    for field in REFERENCE_FIELDS:
        value = mapped.get(field)
        if not value:
            continue
        parent_field = PARENT_FIELDS.get(field)
        parent_value = mapped.get(parent_field) if parent_field else ""
        if parent_field and not parent_value:
            issues.append(issue(row, field, "missing_parent", "error", f"Select {parent_field.replace('_', ' ')} before {field.replace('_', ' ')}."))
            continue
        parent_ref = effective_parent(job, parent_field, parent_value) if parent_field else None
        resolution = _resolution(job, field, value, parent_value)
        if resolution and resolution.decision:
            resolution_actions.add(resolution.decision)
            if resolution.decision == "map" and resolution.resolved_reference_id:
                ref = resolution.resolved_reference
                if not ref.active or ref.kind != REFERENCE_FIELDS[field] or (parent_field and (ref.parent_id != parent_ref.pk if parent_ref else normalize(ref.parent.label if ref.parent else "") != normalize(parent_value))):
                    issues.append(issue(row, field, "invalid_reference_mapping", "error", "Mapped reference is inactive or belongs to a different parent."))
                else:
                    ref_ids[field] = ref.pk
                continue
            if resolution.decision == "create" and resolution.approved:
                continue
            if resolution.decision == "blank":
                mapped[field] = None
                continue
            if resolution.decision in {"skip", "defer"}:
                continue
        matches = _find_reference(field, value, parent_value, parent_ref.pk if parent_ref else None)
        if len(matches) == 1:
            ref_ids[field] = matches[0].pk
        elif len(matches) > 1:
            issues.append(issue(row, field, "ambiguous_reference", "reference", "More than one matching reference exists."))
        else:
            ImportReferenceResolution.objects.get_or_create(
                job=job, field=field, normalized=normalize(value), parent_value=normalize(parent_value),
                defaults={"source_value": str(value)[:180]},
            )
            issues.append(issue(row, field, "missing_reference", "reference", "Reference value was not found.",
                                "Map it, approve its creation, skip, or defer affected rows."))
    mapped["__ref_ids"] = ref_ids
    existing = ServiceItem.objects.filter(facility=job.facility, code=code).first() if code else None
    mode = config.get("mode", "upsert")
    action = "update" if existing else "create"
    if mode == "create" and existing:
        issues.append(issue(row, "code", "existing_conflict", "error", "Service code already exists in this facility."))
    elif mode == "update" and not existing and code:
        issues.append(issue(row, "code", "missing_destination", "error", "Update Only requires an existing item."))
    elif mode == "skip_existing" and existing:
        resolution_actions.add("skip")
    if "skip" in resolution_actions:
        status = "excluded"
    elif any(i.code in {"duplicate_source", "existing_conflict"} for i in issues):
        status = "duplicate"
    elif any(i.severity == "error" for i in issues):
        status = "invalid"
    elif "defer" in resolution_actions or any(i.severity == "reference" for i in issues):
        status = "pending_reference"
    elif any(i.severity == "warning" for i in issues):
        status = "valid_warnings"
    else:
        status = "valid"
    return mapped, action, status, issues


def validation_counts(job):
    return dict(job.rows.values_list("validation_status").annotate(count=Count("id")))


def create_approved_references(job):
    decisions = list(job.resolutions.filter(decision="create", approved=True))
    decisions.sort(key=lambda d: d.field in PARENT_FIELDS)
    for decision in decisions:
        parent = None
        if decision.field in PARENT_FIELDS:
            parent_field = PARENT_FIELDS[decision.field]
            parent = effective_parent(job, parent_field, decision.parent_value)
            if parent is None:
                continue
        try:
            with transaction.atomic():
                ref, _ = ReferenceValue.objects.get_or_create(
                    kind=REFERENCE_FIELDS[decision.field], normalized=decision.normalized, parent=parent,
                    defaults={"label": decision.source_value, "is_demo": True},
                )
                decision.resolved_reference = ref
                decision.save(update_fields=["resolved_reference"])
        except IntegrityError:
            decision.resolved_reference = ReferenceValue.objects.filter(kind=REFERENCE_FIELDS[decision.field], normalized=decision.normalized, parent=parent).first()
            decision.save(update_fields=["resolved_reference"])


def _resolved_ref(job, field, value, mapped):
    parent_field = PARENT_FIELDS.get(field)
    parent_value = mapped.get(parent_field) if parent_field else ""
    parent_ref = effective_parent(job, parent_field, parent_value) if parent_field else None
    decision = _resolution(job, field, value, parent_value)
    if decision:
        if decision.decision == "blank":
            return None
        if decision.decision in {"map", "create"} and decision.resolved_reference_id:
            ref = decision.resolved_reference
            if ref.active and (not parent_field or (ref.parent_id == parent_ref.pk if parent_ref else normalize(ref.parent.label if ref.parent else "") == normalize(parent_value))):
                return ref
            raise ValueError(f"Reference for {field} is inactive or has the wrong parent.")
    matches = _find_reference(field, value, parent_value, parent_ref.pk if parent_ref else None)
    if len(matches) != 1:
        raise ValueError(f"Reference for {field} is missing or ambiguous: {value}")
    return matches[0]


def import_row(row):
    job = row.job
    mapped = row.mapped
    code = mapped.get("code")
    with transaction.atomic():
        existing = ServiceItem.objects.filter(facility=job.facility, code=code).first()
        mode = job.config.get("mode", "upsert")
        if existing and mode == "create":
            raise ValueError("Item now exists; Create Only cannot update it.")
        if not existing and mode == "update":
            raise ValueError("Item no longer exists; Update Only cannot create it.")
        if existing and mode == "skip_existing":
            row.import_status = "skipped"
            row.save(update_fields=["import_status"])
            return "skipped"
        item = existing or ServiceItem(facility=job.facility, code=code)
        blanks = job.config.get("blank_update", "preserve")
        defaults = job.config.get("defaults", {})
        for field, value in mapped.items():
            if field.startswith("__") or field == "code":
                continue
            if value is None and existing and blanks == "preserve":
                continue
            if value is None and existing and blanks == "default":
                value = defaults.get(field)
            if field in REFERENCE_FIELDS:
                value = _resolved_ref(job, field, value, mapped) if value else None
            setattr(item, field, value if value is not None else (None if field in DECIMAL_FIELDS | BOOLEAN_FIELDS | {"discontinued_date"} | set(REFERENCE_FIELDS) else ""))
        item.full_clean(exclude=["facility"])
        item.save()
        row.destination = item
        row.import_status = "updated" if existing else "created"
        row.save(update_fields=["destination", "import_status"])
        return row.import_status
