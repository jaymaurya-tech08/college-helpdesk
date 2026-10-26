
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from config.views import landing_page
from helpdesk import views as helpdesk_views


urlpatterns = [
    path("admin/", admin.site.urls),

    # Landing page
    path("", landing_page, name="home"),

    # Accounts
    path("accounts/", include("accounts.urls")),

    # Dashboards
    path("dashboard/", include("dashboard.urls")),

    # Helpdesk application
    path("helpdesk/", include("helpdesk.urls")),
    # ← Add this
    path("attendance/", include("attendance.urls")),

    # Faculty directory
    path(
        "departments/",
        helpdesk_views.department_directory,
        name="department_directory",
    ),

    path(
        "faculty/",
        helpdesk_views.department_directory,
        name="faculty_directory",
    ),
]

if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )
