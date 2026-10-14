from .models import Facility


def prototype_context(request):
    facility_id = request.session.get("facility_id")
    facility = Facility.objects.filter(pk=facility_id).first() if facility_id else None
    return {"current_facility": facility or Facility.objects.first(), "facilities": Facility.objects.all()}
