from django.contrib import admin
from .models import StudentFace, AttendanceRecord

@admin.register(StudentFace)
class StudentFaceAdmin(admin.ModelAdmin):
    list_display = ("student", "is_active", "registered_at")
    search_fields = ("student__username", "student__email", "student__first_name")
    list_filter = ("is_active",)

@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ("student", "date", "time", "class_session", "status", "confidence", "method")
    list_filter = ("date", "status", "method")
    search_fields = ("student__username", "student__first_name", "class_session")
    date_hierarchy = "date"