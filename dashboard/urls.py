from django.urls import path
from dashboard.views.dashboard import DashboardView, DashboardRedirectView
from dashboard.views.facilities_maintenance import FacilitiesMaintenanceView
from dashboard.views.add_facilities import AddFacilitiesMaintenanceView
from dashboard.views.edit_maintenance import EditFacilitiesMaintenanceView
from dashboard.views.maintenance_detail import MaintenanceDetailView
from dashboard.views.facility_detail import FacilityDetailView
from dashboard.views.edit_facility import EditFacilityView
from dashboard.views.inventory import InventoryView
from dashboard.views.reservations import ReservationsCalendarView
from dashboard.views.reservation_detail import ReservationDetailView
from dashboard.views.create_reservation import (
    CreateBookingView,
    CreateReservationView,
)
from dashboard.views.calendar_entries import (
    CalendarDayEntriesView,
    CreateUnavailableView,
    EditCalendarEntryView,
    RemoveCalendarEntryView,
)

urlpatterns = [
    path('', DashboardRedirectView.as_view()),
    path('<str:branch>/', DashboardView.as_view()),
    path(
        '<str:branch>/inventory/',
        InventoryView.as_view(),
        name='inventory',
    ),
    path(
        '<str:branch>/reservations/',
        ReservationsCalendarView.as_view(),
        name='reservations',
    ),
    path(
        '<str:branch>/reservations/new/',
        CreateReservationView.as_view(),
        name='create-reservation',
    ),
    path(
        '<str:branch>/reservations/booking/new/',
        CreateBookingView.as_view(),
        name='create-booking',
    ),
    path(
        '<str:branch>/reservations/<int:reservation_id>/',
        ReservationDetailView.as_view(),
        name='reservation-detail',
    ),
    path(
        '<str:branch>/reservations/calendar/day/',
        CalendarDayEntriesView.as_view(),
        name='calendar-day-entries',
    ),
    path(
        '<str:branch>/reservations/unavailable/new/',
        CreateUnavailableView.as_view(),
        name='create-unavailable',
    ),
    path(
        '<str:branch>/reservations/calendar/<int:entry_id>/edit/',
        EditCalendarEntryView.as_view(),
        name='edit-calendar-entry',
    ),
    path(
        '<str:branch>/reservations/calendar/<int:entry_id>/remove/',
        RemoveCalendarEntryView.as_view(),
        name='remove-calendar-entry',
    ),
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
    path(
        '<str:branch>/<str:facility_slug>/edit/',
        EditFacilityView.as_view(),
        name='edit-facility',
    ),
    path(
        '<str:branch>/<str:facility_slug>/',
        FacilityDetailView.as_view(),
        name='facility-detail',
    ),
]