from django.urls import path
from dashboard.views.dashboard import DashboardView, DashboardRedirectView
from dashboard.views.facilities_maintenance import FacilitiesMaintenanceView
from dashboard.views.add_facilities import AddFacilitiesMaintenanceView

urlpatterns = [
    path('', DashboardRedirectView.as_view()),
    path('<str:branch>/', DashboardView.as_view()),
    path('<str:branch>/facilities-and-maintenance/', FacilitiesMaintenanceView.as_view()),
    path('<str:branch>/add-maintenance/', AddFacilitiesMaintenanceView.as_view())
]