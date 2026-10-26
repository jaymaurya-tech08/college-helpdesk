from django.db import models
from django.conf import settings
from django.utils import timezone


class StudentFace(models.Model):
    student = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="face_profile",
        limit_choices_to={"role": "STUDENT"},
    )
    # Store multiple embeddings as a list of lists
    embeddings = models.JSONField(default=list)
    registered_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.student.get_full_name() or self.student.username} Face"


class AttendanceRecord(models.Model):
    STATUS_CHOICES = (
        ("Present", "Present"),
        ("Absent", "Absent"),
        ("Late", "Late"),
    )

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="attendance_records",
        limit_choices_to={"role": "STUDENT"},
    )
    date = models.DateField(default=timezone.localdate)
    time = models.TimeField(auto_now_add=True)
    class_session = models.CharField(max_length=150)  # e.g. "Period-1 Data Structures"
    subject = models.CharField(max_length=100, blank=True)
    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="marked_attendances",
    )
    confidence = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="Present")
    method = models.CharField(max_length=20, default="webcam")  # webcam / photo

    class Meta:
        unique_together = ("student", "date", "class_session")
        ordering = ["-date", "-time"]

    def __str__(self):
        return f"{self.student} | {self.date} | {self.class_session}"
