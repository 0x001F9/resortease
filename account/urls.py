from django.urls import path
from account.views.logout import LogoutView
from account.views.login import EmailVerificationView
from account.views.signup import SignUpView
from account.views.security import (
    ChangeTOTPAuthenticatorView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    TOTPSetupView,
    TOTPVerificationView,
    UpdateTOTPSettingsView,
)
from account.views import UserProfileView, UserSettingsView

urlpatterns = [
    path('u/<str:username>/settings/', UserSettingsView.as_view(), name='user-settings'),
    path('u/<str:username>/', UserProfileView.as_view(), name='user-profile'),
    path('sign-up/', SignUpView.as_view(), name='sign-up'),
    path('verify-email/<str:token>/', EmailVerificationView.as_view(), name='verify-email'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('forgot-password/', PasswordResetRequestView.as_view(), name='forgot-password'),
    path('reset-password/', PasswordResetConfirmView.as_view(), name='reset-password'),
    path('security/totp/setup/', TOTPSetupView.as_view(), name='totp-setup'),
    path('security/totp/verify/', TOTPVerificationView.as_view(), name='totp-verify'),
    path(
        'u/<str:username>/settings/totp/change/',
        ChangeTOTPAuthenticatorView.as_view(),
        name='change-totp-authenticator',
    ),
    path(
        'u/<str:username>/settings/totp/',
        UpdateTOTPSettingsView.as_view(),
        name='update-totp-settings',
    ),
]