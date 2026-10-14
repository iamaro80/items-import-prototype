from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("items/", views.items, name="items"),
    path("items/<int:pk>/", views.item_detail, name="item_detail"),
    path("items/export/", views.export_items, name="export_items"),
    path("sample/", views.download_sample, name="download_sample"),
    path("import/new/", views.import_new, name="import_new"),
    path("import/<int:pk>/", views.import_job, name="import_job"),
    path("import/<int:pk>/mapping/", views.mapping, name="mapping"),
    path("import/<int:pk>/configure/", views.configure, name="configure"),
    path("import/<int:pk>/validate/", views.start_validation, name="start_validation"),
    path("import/<int:pk>/issues/", views.issues, name="issues"),
    path("import/<int:pk>/references/", views.resolve_references, name="resolve_references"),
    path("import/<int:pk>/confirm/", views.confirm_import, name="confirm_import"),
    path("import/<int:pk>/progress/", views.progress, name="progress"),
    path("import/<int:pk>/control/", views.control_job, name="control_job"),
    path("import/<int:pk>/report/<str:kind>/", views.report, name="report"),
    path("history/", views.history, name="history"),
    path("references/", views.references, name="references"),
    path("demo/", views.demo, name="demo"),
    path("facility/", views.select_facility, name="select_facility"),
]
