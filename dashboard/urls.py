from django.urls import path
from dashboard.views.dashboard import DashboardView

urlpatterns = [
    path('', DashboardView.as_view())
]