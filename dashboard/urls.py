from django.urls import path
from dashboard.views.dashboard import DashboardView, DashboardRedirectView
from dashboard.views.facilities_maintenance import FacilitiesMaintenanceView

urlpatterns = [
    path('', DashboardRedirectView.as_view()),
    path('<str:branch>/', DashboardView.as_view()),
    path('<str:branch>/facilities-and-maintenance/', FacilitiesMaintenanceView.as_view())
]