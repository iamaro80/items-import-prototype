from django.core.management.base import BaseCommand
from core.models import Facility, ReferenceValue
from core.schema import normalize


class Command(BaseCommand):
    help = "Create deterministic, explicitly fictional reference fixtures; some CSV values stay missing."

    def handle(self, *args, **options):
        Facility.objects.get_or_create(code="KAMC-AH-DEMO", defaults={"name": "King Abdulaziz Medical City – Al Ahsa (Demo)"})
        Facility.objects.get_or_create(code="UAT-DEMO", defaults={"name": "UAT Hospital (Demo)"})

        def add(kind, label, parent=None):
            obj, _ = ReferenceValue.objects.get_or_create(
                kind=kind, normalized=normalize(label), parent=parent,
                defaults={"label": label, "is_demo": True},
            )
            return obj

        pharma = add("chapter", "Pharmaceuticals")
        other = add("chapter", "Other Services")
        add("block", "Other", pharma)
        add("block", "Other", other)  # same child label, different parent
        add("block", "Examination procedures on external ear", pharma)
        add("tax_category", "0%")
        add("tax_category", "15%")
        add("service_type", "MedicationCodes")
        add("service_type", "Laboratory")
        add("service_type", "TransportationSrca")
        add("cost_center", "(Both) - DB-151")
        add("sub_cost_center", "(123) - ssdf", ReferenceValue.objects.get(kind="cost_center", normalized=normalize("(Both) - DB-151")))
        dept = add("department", "36856")
        add("sub_department", "36856", dept)
        add("category", "DIC0031C1")
        for kind, value in [
            ("strength_unit", "U-3"), ("pharmaceutical_form", "GRANULES"),
            ("administration_route", "OCULAR"), ("package_type", "VIAL"),
            ("product_control", "Controlled"), ("distribution_area", "Hospital"),
        ]:
            add(kind, value)
        self.stdout.write(self.style.SUCCESS("Demo facilities and reference fixtures are ready."))
