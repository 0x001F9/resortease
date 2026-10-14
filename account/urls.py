from django.urls import path
from account.views.logout import LogoutView
from account.views.login import EmailVerificationView
from account.views.security import (
    PasswordResetConfirmView,
    PasswordResetRequestView,
    TOTPSetupView,
    TOTPVerificationView,
)

urlpatterns = [
    path('verify-email/<str:token>/', EmailVerificationView.as_view(), name='verify-email'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('forgot-password/', PasswordResetRequestView.as_view(), name='forgot-password'),
    path('reset-password/', PasswordResetConfirmView.as_view(), name='reset-password'),
    path('security/totp/setup/', TOTPSetupView.as_view(), name='totp-setup'),
    path('security/totp/verify/', TOTPVerificationView.as_view(), name='totp-verify'),
]