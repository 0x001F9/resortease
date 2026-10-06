from django.urls import path
from dashboard.views.dashboard import DashboardView, DashboardRedirectView
from dashboard.views.facilities_maintenance import FacilitiesMaintenanceView
from dashboard.views.add_facilities import AddFacilitiesMaintenanceView
from dashboard.views.edit_maintenance import EditFacilitiesMaintenanceView
from dashboard.views.maintenance_detail import MaintenanceDetailView

urlpatterns = [
    path('', DashboardRedirectView.as_view()),
    path('<str:branch>/', DashboardView.as_view()),
    path('<str:branch>/facilities-and-maintenance/', FacilitiesMaintenanceView.as_view()),
    path('<str:branch>/add-maintenance/', AddFacilitiesMaintenanceView.as_view()),
    path(
        '<str:branch>/maintenance/<int:maintenance_id>/edit/',
        EditFacilitiesMaintenanceView.as_view(),
        name='edit-maintenance',
    ),
    path(
        '<str:branch>/maintenance/<int:maintenance_id>/',
        MaintenanceDetailView.as_view(),
        name='maintenance-detail',
    ),
]