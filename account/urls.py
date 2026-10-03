from django.urls import path
from account.views.logout import LogoutView

urlpatterns = [
    path('logout/', LogoutView.as_view(), name='logout'),
]