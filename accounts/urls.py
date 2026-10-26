from django.urls import path
from django.contrib.auth import views as auth_views
from django.contrib.auth.views import LogoutView
from . import views


app_name = "accounts"


urlpatterns = [
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="accounts/login.html"
        ),
        name="login",
    ),
    path(
        "password-reset/",
        views.password_reset_request,
        name="password_reset",
    ),
    path(
        "password-reset/verify/",
        views.password_reset_verify,
        name="password_reset_verify",
    ),
    path(
        "password-reset/new-password/",
        views.password_reset_confirm,
        name="password_reset_confirm",
    ),

    path(
        "register/",
        views.register,
        name="register",
    ),

    path(
        "logout/",
        LogoutView.as_view(next_page="accounts:login"),
        name="logout",
    ),

    path(
    "verify-email/",
    views.verify_email,
    name="verify_email",
),

path("profile/", views.profile, name="profile"),
path("profile/edit/", views.edit_profile, name="edit_profile"),

]
