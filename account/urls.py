from django.urls import path
from account.views.logout import LogoutView
from account.views.login import EmailVerificationView
from account.views.security import (
    PasswordResetConfirmView,
    PasswordResetRequestView,
    TOTPSetupView,
    TOTPVerificationView,
    change_totp_authenticator,
    update_totp_settings,
)
from account.views import user_profile, user_settings

urlpatterns = [
    path('u/<str:username>/settings/', user_settings, name='user-settings'),
    path('u/<str:username>/', user_profile, name='user-profile'),
    path('verify-email/<str:token>/', EmailVerificationView.as_view(), name='verify-email'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('forgot-password/', PasswordResetRequestView.as_view(), name='forgot-password'),
    path('reset-password/', PasswordResetConfirmView.as_view(), name='reset-password'),
    path('security/totp/setup/', TOTPSetupView.as_view(), name='totp-setup'),
    path('security/totp/verify/', TOTPVerificationView.as_view(), name='totp-verify'),
    path(
        'u/<str:username>/settings/totp/change/',
        change_totp_authenticator,
        name='change-totp-authenticator',
    ),
    path(
        'u/<str:username>/settings/totp/',
        update_totp_settings,
        name='update-totp-settings',
    ),
]