import os
import logging
import time
import cv2
import numpy as np
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from django.db import transaction

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import StreamingHttpResponse, JsonResponse
from django.db import close_old_connections
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.core.paginator import Paginator
from django.utils.dateparse import parse_date

from accounts.models import User
from .models import StudentFace, AttendanceRecord
from .face_service import (
    estimate_face_pose,
    register_student_face,
    recognize_face,
    recognize_faces,
)

logger = logging.getLogger(__name__)
PHOTO_ATTENDANCE_PREVIEW_KEY = "attendance_photo_preview"
PHOTO_ATTENDANCE_PREVIEW_MINUTES = 5


def _recognize_frame(frame):
    close_old_connections()
    try:
        return recognize_face(frame)
    finally:
        close_old_connections()


# ---------------------------------------------------------
# Permission helpers
# ---------------------------------------------------------

def staff_required(view_func):
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("accounts:login")
        if not (request.user.is_staff_member or request.user.is_admin_user):
            messages.error(request, "Only staff/teachers can access this page.")
            return redirect("dashboard:dashboard")
        return view_func(request, *args, **kwargs)
    return wrapper


def admin_required(view_func):
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_admin_user:
            messages.error(request, "Admin access required.")
            return redirect("dashboard:dashboard")
        return view_func(request, *args, **kwargs)
    return wrapper


# ---------------------------------------------------------
# Teacher – Register Student Face
# ---------------------------------------------------------

@login_required
@staff_required
def register_face(request):
    students = User.objects.filter(role=User.Roles.STUDENT).order_by("first_name")

    if request.method == "POST":
        student_id = request.POST.get("student_id")
        live_photos = request.FILES.getlist("live_photos")
        manual_photos = request.FILES.getlist("photos")

        if not student_id:
            messages.error(request, "Please select a student.")
            return redirect("attendance:register_face")
        if len(live_photos) != 5:
            messages.error(
                request,
                "Complete all five guided live camera captures before registering this face.",
            )
            return redirect("attendance:register_face")

        student = get_object_or_404(User, id=student_id, role=User.Roles.STUDENT)

        temp_paths = []
        live_temp_paths = []
        try:
            for photo in manual_photos:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    for chunk in photo.chunks():
                        tmp.write(chunk)
                    temp_paths.append(tmp.name)

            for photo in live_photos:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    for chunk in photo.chunks():
                        tmp.write(chunk)
                    temp_paths.append(tmp.name)
                    live_temp_paths.append(tmp.name)

            success, message = register_student_face(
                student,
                temp_paths,
                required_image_paths=live_temp_paths,
            )
        except Exception:
            logger.exception("Face registration failed for student %s", student.pk)
            messages.error(
                request,
                "Face recognition could not process these photos. Check that the face model is installed and try again.",
            )
        else:
            if success:
                messages.success(request, f"{message} Live frames: {len(live_photos)}.")
            else:
                messages.error(request, message)
        finally:
            for path in temp_paths:
                try:
                    os.remove(path)
                except FileNotFoundError:
                    pass

        return redirect("attendance:register_face")

    return render(request, "attendance/register_face.html", {
        "students": students
    })


# ---------------------------------------------------------
# Teacher – Take Attendance (Main Page)
# ---------------------------------------------------------

@login_required
@staff_required
def take_attendance(request):
    students = User.objects.filter(
        role=User.Roles.STUDENT,
        is_active=True,
        face_profile__is_active=True,
    )

    if request.user.is_staff_member:
        staff_profile = getattr(request.user, "staff_profile", None)
        department = (
            staff_profile.department
            if staff_profile and staff_profile.department_id
            else request.user.department
        )
        if department:
            students = students.filter(department=department)

    students = students.order_by("first_name", "last_name", "username")
    return render(request, "attendance/take_attendance.html", {
        "students": students,
    })


@login_required
@staff_required
@require_POST
def face_pose_check(request):
    frame = request.FILES.get("frame")
    if not frame:
        return JsonResponse({"success": False, "message": "No camera frame was received."}, status=400)
    if frame.size > 3 * 1024 * 1024:
        return JsonResponse({"success": False, "message": "Camera frame is too large."}, status=400)

    image = cv2.imdecode(np.frombuffer(frame.read(), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return JsonResponse({"success": False, "message": "Could not read this camera frame."}, status=400)

    try:
        pose = estimate_face_pose(image)
    except Exception:
        logger.exception("Live face pose analysis failed")
        return JsonResponse({"success": False, "message": "Live face analysis is unavailable."}, status=503)

    if pose is None:
        return JsonResponse({"success": True, "face_detected": False})
    if pose["face_count"] != 1:
        return JsonResponse({"success": True, "face_detected": True, "face_count": pose["face_count"], "multiple_faces": True})

    return JsonResponse({
        "success": True,
        "face_detected": True,
        "face_count": 1,
        "yaw": pose["yaw"],
        "pitch": pose["pitch"],
    })


# ---------------------------------------------------------
# Live Webcam Stream + Auto Mark
# ---------------------------------------------------------

def generate_frames(request, class_session):
    camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not camera.isOpened():
        camera.release()
        camera = cv2.VideoCapture(0)

    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    recognition_worker = ThreadPoolExecutor(max_workers=1)
    recognition_task = None
    recognized_student = None
    recognized_score = 0.0
    attendance_status = {}
    frame_count = 0
    last_frame_time = 0.0

    try:
        if not camera.isOpened():
            logger.error("Could not open the server webcam for attendance")
            frame = np.zeros((360, 640, 3), dtype=np.uint8)
            cv2.putText(frame, "Camera unavailable on this server", (35, 180),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
            ret, buffer = cv2.imencode(".jpg", frame)
            if ret:
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'
                       + buffer.tobytes() + b'\r\n')
            return

        while True:
            success, frame = camera.read()
            if not success:
                break

            height, width = frame.shape[:2]
            scale = min(640 / width, 480 / height, 1.0)
            if scale < 1.0:
                frame = cv2.resize(
                    frame,
                    (int(width * scale), int(height * scale)),
                    interpolation=cv2.INTER_AREA,
                )

            if recognition_task is not None and recognition_task.done():
                try:
                    recognized_student, recognized_score = recognition_task.result()
                    if recognized_student and recognized_student.pk not in attendance_status:
                        _, created = AttendanceRecord.objects.get_or_create(
                            student=recognized_student,
                            date=timezone.localdate(),
                            class_session=class_session,
                            defaults={
                                "marked_by": request.user,
                                "confidence": recognized_score,
                                "status": "Present",
                                "method": "webcam",
                            },
                        )
                        attendance_status[recognized_student.pk] = (
                            "Attendance marked" if created else "Already marked"
                        )
                except Exception:
                    logger.exception("Webcam face recognition failed")
                    recognized_student = None
                    recognized_score = 0.0
                recognition_task = None

            if recognition_task is None and frame_count % 8 == 0:
                recognition_task = recognition_worker.submit(
                    _recognize_frame,
                    frame.copy(),
                )

            if recognized_student:
                label = recognized_student.get_full_name() or recognized_student.username
                cv2.putText(frame, label, (20, 32), cv2.FONT_HERSHEY_SIMPLEX,
                            0.7, (0, 255, 0), 2)
                cv2.putText(frame, f"Score: {recognized_score:.2f}", (20, 62),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)
                status = attendance_status.get(recognized_student.pk)
                if status:
                    cv2.putText(frame, status, (20, 92), cv2.FONT_HERSHEY_SIMPLEX,
                                0.6, (0, 255, 0), 2)
            else:
                cv2.putText(frame, "Looking for a recognized face...", (20, 32),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 200, 255), 2)

            ret, buffer = cv2.imencode(
                ".jpg",
                frame,
                [cv2.IMWRITE_JPEG_QUALITY, 75],
            )
            if not ret:
                continue
            frame_bytes = buffer.tobytes()

            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            frame_count += 1

            frame_delay = 1 / 20 - (time.monotonic() - last_frame_time)
            if frame_delay > 0:
                time.sleep(frame_delay)
            last_frame_time = time.monotonic()
    finally:
        camera.release()
        recognition_worker.shutdown(wait=False, cancel_futures=True)


@login_required
@staff_required
def video_feed(request):
    class_session = request.GET.get("session", "General Class").strip()[:150]
    return StreamingHttpResponse(
        generate_frames(request, class_session),
        content_type='multipart/x-mixed-replace; boundary=frame'
    )


# ---------------------------------------------------------
# Photo Upload Attendance
# ---------------------------------------------------------

@login_required
@staff_required
@require_POST
def photo_attendance(request):
    action = request.POST.get("action", "preview")

    if action == "cancel":
        request.session.pop(PHOTO_ATTENDANCE_PREVIEW_KEY, None)
        return JsonResponse({"success": True, "stage": "cancelled"})

    if action == "confirm":
        pending = request.session.get(PHOTO_ATTENDANCE_PREVIEW_KEY)
        if not pending or pending.get("user_id") != request.user.pk:
            return JsonResponse(
                {"success": False, "message": "This preview has expired. Upload the photo again."},
                status=400,
            )

        expires_at = datetime.fromisoformat(pending["expires_at"])
        if timezone.now() >= expires_at:
            request.session.pop(PHOTO_ATTENDANCE_PREVIEW_KEY, None)
            return JsonResponse(
                {"success": False, "message": "This preview has expired. Upload the photo again."},
                status=400,
            )

        student_ids = pending["student_ids"]
        allowed_students = User.objects.filter(
            role=User.Roles.STUDENT,
            is_active=True,
            face_profile__is_active=True,
        )
        if request.user.is_staff_member:
            staff_profile = getattr(request.user, "staff_profile", None)
            department = (
                staff_profile.department
                if staff_profile and staff_profile.department_id
                else request.user.department
            )
            if department:
                allowed_students = allowed_students.filter(department=department)

        roster = list(
            allowed_students.filter(pk__in=student_ids)
            .only("id", "first_name", "last_name", "username")
            .order_by("first_name", "last_name", "username")
        )
        if len(roster) != len(student_ids):
            request.session.pop(PHOTO_ATTENDANCE_PREVIEW_KEY, None)
            return JsonResponse(
                {"success": False, "message": "The class roster changed. Upload the photo again."},
                status=400,
            )

        present_scores = {
            int(student_id): float(score)
            for student_id, score in pending["present_scores"].items()
        }
        roster_by_id = {student.pk: student for student in roster}
        today = date.fromisoformat(pending["date"])
        class_session = pending["class_session"]
        to_create = []
        to_update = []
        existing_records = {
            record.student_id: record
            for record in AttendanceRecord.objects.filter(
                student_id__in=student_ids,
                date=today,
                class_session=class_session,
            )
        }

        for student in roster:
            confidence = present_scores.get(student.pk)
            status = "Present" if confidence is not None else "Absent"
            record = existing_records.get(student.pk)
            if record is None:
                to_create.append(AttendanceRecord(
                    student=student,
                    date=today,
                    class_session=class_session,
                    marked_by=request.user,
                    confidence=confidence,
                    status=status,
                    method="photo",
                ))
            else:
                record.marked_by = request.user
                record.confidence = confidence
                record.status = status
                record.method = "photo"
                to_update.append(record)

        with transaction.atomic():
            if to_create:
                AttendanceRecord.objects.bulk_create(to_create)
            if to_update:
                AttendanceRecord.objects.bulk_update(
                    to_update,
                    ["marked_by", "confidence", "status", "method"],
                )

        absent_ids = set(student_ids) - set(present_scores)
        request.session.pop(PHOTO_ATTENDANCE_PREVIEW_KEY, None)
        request.session.modified = True
        return JsonResponse({
            "success": True,
            "stage": "confirmed",
            "message": (
                f"Attendance saved for {len(roster)} students: "
                f"{len(present_scores)} present, {len(absent_ids)} absent."
            ),
            "present_count": len(present_scores),
            "absent_count": len(absent_ids),
            "faces_detected": pending["faces_detected"],
            "unmatched_faces": pending["unmatched_faces"],
            "present_students": [
                roster_by_id[student_id].get_full_name() or roster_by_id[student_id].username
                for student_id in present_scores
            ],
            "absent_students": [
                roster_by_id[student_id].get_full_name() or roster_by_id[student_id].username
                for student_id in absent_ids
            ],
        })

    if action != "preview":
        return JsonResponse({"success": False, "message": "Unknown attendance action."}, status=400)

    request.session.pop(PHOTO_ATTENDANCE_PREVIEW_KEY, None)
    class_session = request.POST.get("class_session", "General Class").strip()[:150]
    photo = request.FILES.get("photo")
    try:
        student_ids = list(dict.fromkeys(
            int(student_id)
            for student_id in request.POST.getlist("expected_students")
        ))
    except (TypeError, ValueError):
        return JsonResponse(
            {"success": False, "message": "The selected student list is invalid."},
            status=400,
        )

    if not photo:
        return JsonResponse({"success": False, "message": "No class photo uploaded."}, status=400)
    if not class_session:
        return JsonResponse({"success": False, "message": "Enter a class session name."}, status=400)
    if not student_ids:
        return JsonResponse(
            {"success": False, "message": "Select the students who belong to this class session."},
            status=400,
        )
    allowed_students = User.objects.filter(
        role=User.Roles.STUDENT,
        is_active=True,
        face_profile__is_active=True,
    )
    if request.user.is_staff_member:
        staff_profile = getattr(request.user, "staff_profile", None)
        department = (
            staff_profile.department
            if staff_profile and staff_profile.department_id
            else request.user.department
        )
        if department:
            allowed_students = allowed_students.filter(department=department)

    roster = list(
        allowed_students.filter(pk__in=student_ids)
        .only("id", "first_name", "last_name", "username")
        .order_by("first_name", "last_name", "username")
    )
    if len(roster) != len(student_ids):
        return JsonResponse(
            {"success": False, "message": "The selected class roster is invalid. Refresh and select the students again."},
            status=400,
        )

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            for chunk in photo.chunks():
                tmp.write(chunk)
            temp_path = tmp.name

        matches, face_count = recognize_faces(temp_path)
    except Exception:
        logger.exception("Photo attendance face recognition failed")
        return JsonResponse(
            {"success": False, "message": "Face recognition is unavailable. Check that the face model is installed."},
            status=503,
        )
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

    if face_count == 0:
        return JsonResponse(
            {"success": False, "message": "No faces were detected. Attendance was not changed."},
            status=400,
        )

    roster_by_id = {student.pk: student for student in roster}
    matches_by_id = {
        student.pk: (student, score)
        for student, score in matches
        if student.pk in roster_by_id
    }
    matched_face_count = len(matches)
    unmatched_face_count = max(face_count - matched_face_count, 0)
    outside_roster_count = matched_face_count - len(matches_by_id)
    present_scores = {
        str(student_id): score
        for student_id, (_, score) in matches_by_id.items()
    }
    request.session[PHOTO_ATTENDANCE_PREVIEW_KEY] = {
        "user_id": request.user.pk,
        "student_ids": student_ids,
        "present_scores": present_scores,
        "class_session": class_session,
        "date": timezone.localdate().isoformat(),
        "faces_detected": face_count,
        "unmatched_faces": unmatched_face_count + outside_roster_count,
        "expires_at": (
            timezone.now() + timedelta(minutes=PHOTO_ATTENDANCE_PREVIEW_MINUTES)
        ).isoformat(),
    }
    request.session.modified = True
    return JsonResponse({
        "success": True,
        "stage": "preview",
        "message": (
            f"Preview ready for {len(roster)} students: "
            f"{len(matches_by_id)} present, {len(roster) - len(matches_by_id)} absent. "
            "No attendance has been saved yet."
        ),
        "present_count": len(matches_by_id),
        "absent_count": len(roster) - len(matches_by_id),
        "faces_detected": face_count,
        "unmatched_faces": unmatched_face_count + outside_roster_count,
        "present_students": [
            roster_by_id[student_id].get_full_name() or roster_by_id[student_id].username
            for student_id in matches_by_id
        ],
        "absent_students": [
            student.get_full_name() or student.username
            for student in roster
            if student.pk not in matches_by_id
        ],
    })


# ---------------------------------------------------------
# Student – View Own Attendance
# ---------------------------------------------------------

@login_required
def my_attendance(request):
    if not request.user.is_student:
        messages.error(request, "Only students can view this page.")
        return redirect("dashboard:dashboard")

    records = AttendanceRecord.objects.filter(student=request.user).order_by("-date", "-time")
    return render(request, "attendance/my_attendance.html", {
        "records": records
    })


# ---------------------------------------------------------
# Admin / Staff – View All Attendance
# ---------------------------------------------------------

@login_required
@staff_required
def all_attendance(request):
    date_filter = request.GET.get("date", "").strip()
    records = AttendanceRecord.objects.select_related("student", "marked_by").all()

    if date_filter:
        parsed_date = parse_date(date_filter)
        if parsed_date:
            records = records.filter(date=parsed_date)
        else:
            date_filter = ""

    return render(request, "attendance/all_attendance.html", {
        "records": Paginator(records, 50).get_page(request.GET.get("page")),
        "selected_date": date_filter,
    })
