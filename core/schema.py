"""Editable prototype field and reference rules. Source spelling is intentionally retained."""
SOURCE_TO_TARGET = {
    "Code": "code", "ShortDescription": "short_description", "LongDesription": "long_description",
    "HospitalCode": "hospital_code", "HospitalDescription": "hospital_description", "IsListed": "is_listed",
    "IsPackge": "is_package", "Alias": "alias", "Chapter": "chapter", "Block": "block",
    "CostCenter": "cost_center", "SubCostCenter": "sub_cost_center", "Department": "department",
    "SubDepatment": "sub_department", "Category": "category", "TaxCategory": "tax_category",
    "Type": "service_type", "MaterialCost": "material_cost", "RegisterNumber": "registration_number",
    "ScientificName": "scientific_name", "ScientificCode": "scientific_code",
    "DescriptionCode": "description_code", "Strength": "strength", "StrengthUnit": "strength_unit",
    "PharmaceuticalForm": "pharmaceutical_form", "AdministrationRoute": "administration_route",
    "PackageTypes": "package_type", "PackageSize": "package_size", "ProductControl": "product_control",
    "DistributeArea": "distribution_area", "DiscontinuedDate": "discontinued_date",
    "PublicPrice": "public_price", "Status": "status",
}
TARGET_FIELDS = list(SOURCE_TO_TARGET.values())
REFERENCE_FIELDS = {
    "chapter": "chapter", "block": "block", "cost_center": "cost_center",
    "sub_cost_center": "sub_cost_center", "department": "department",
    "sub_department": "sub_department", "category": "category",
    "tax_category": "tax_category", "service_type": "service_type",
    "strength_unit": "strength_unit", "pharmaceutical_form": "pharmaceutical_form",
    "administration_route": "administration_route", "package_type": "package_type",
    "product_control": "product_control", "distribution_area": "distribution_area",
}
PARENT_FIELDS = {"block": "chapter", "sub_cost_center": "cost_center", "sub_department": "department"}
BOOLEAN_FIELDS = {"is_listed", "is_package"}
DECIMAL_FIELDS = {"material_cost", "public_price"}
REQUIRED_FIELDS = {"code"}
STATUS_VALUES = {"Active", "Inactive"}


def normalize(value):
    return " ".join(str(value or "").strip().casefold().split())


def suggested_mapping(headers):
    return {header: SOURCE_TO_TARGET.get(header, "") for header in headers}
