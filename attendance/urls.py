from django.urls import path
from . import views

app_name = "attendance"

urlpatterns = [
    # Teacher
    path("register-face/", views.register_face, name="register_face"),
    path("face-pose-check/", views.face_pose_check, name="face_pose_check"),
    path("take/", views.take_attendance, name="take_attendance"),
    path("video-feed/", views.video_feed, name="video_feed"),
    path("photo-upload/", views.photo_attendance, name="photo_attendance"),

    # Student
    path("my/", views.my_attendance, name="my_attendance"),

    # Staff / Admin
    path("all/", views.all_attendance, name="all_attendance"),
]
