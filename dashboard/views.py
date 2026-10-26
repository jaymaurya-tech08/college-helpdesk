from django.contrib.auth.decorators import login_required

from django.contrib.auth import get_user_model


from django.views.decorators.http import require_POST

from helpdesk.models import Request, Department
from attendance.models import AttendanceRecord
from django.contrib import messages


from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Q, query



User = get_user_model()


@login_required
def dashboard(request):

    user = request.user

    # =========================
    # STUDENT DASHBOARD
    # =========================
    if user.role == user.Roles.STUDENT:

        student_requests = Request.objects.filter(
            student=user
        )

        total_requests = student_requests.count()

        pending_requests = student_requests.filter(
            status=Request.Status.PENDING
        ).count()

        in_progress_requests = student_requests.filter(
            status=Request.Status.IN_PROGRESS
        ).count()

        resolved_requests = student_requests.filter(
            status__in=[
                Request.Status.RESOLVED,
                Request.Status.CLOSED,
            ]
        ).count()

        recent_requests = (
            student_requests
            .select_related(
                "department",
                "category",
            )
            .order_by("-created_at")[:5]
        )

        return render(
            request,
            "dashboard/dashboard.html",
            {
                "dashboard_type": "student",
                "title": "Student Dashboard",

                "total_requests": total_requests,
                "pending_requests": pending_requests,
                "in_progress_requests": in_progress_requests,
                "resolved_requests": resolved_requests,

                "recent_requests": recent_requests,
            }
        )

    # =========================
    # STAFF DASHBOARD
    # =========================
    if user.role == user.Roles.STAFF:

        assigned_requests = Request.objects.filter(
            assigned_staff=user
        )

        pending_requests = assigned_requests.filter(
            status=Request.Status.PENDING
        ).count()

        in_progress_requests = assigned_requests.filter(
            status=Request.Status.IN_PROGRESS
        ).count()

        resolved_requests = assigned_requests.filter(
            status__in=[
                Request.Status.RESOLVED,
                Request.Status.CLOSED,
            ]
        ).count()

        recent_requests = (
            assigned_requests
            .select_related(
                "student",
                "department",
                "category",
            )
            .order_by("-created_at")[:5]
        )

        return render(
            request,
            "dashboard/dashboard.html",
            {
                "dashboard_type": "staff",
                "title": "Staff Dashboard",

                "assigned_requests": assigned_requests.count(),
                "pending_requests": pending_requests,
                "in_progress_requests": in_progress_requests,
                "resolved_requests": resolved_requests,

                "recent_requests": recent_requests,
            }
        )

    # =========================
    # ADMIN
    # =========================
    if user.role == user.Roles.ADMIN:

        return redirect("dashboard:admin_dashboard")

    # =========================
    # UNKNOWN ROLE
    # =========================

    return redirect("accounts:login")


# ============================================================
# ADMIN DASHBOARD
# ============================================================

@login_required
def admin_dashboard(request):

    user = request.user

    # Only ADMIN can access this page
    if user.role != user.Roles.ADMIN:
        return redirect("dashboard:dashboard")

    total_students = User.objects.filter(
        role=user.Roles.STUDENT
    ).count()

    total_staff = User.objects.filter(
        role=user.Roles.STAFF
    ).count()

    total_requests = Request.objects.count()
    total_attendance = AttendanceRecord.objects.count()

    pending_requests = Request.objects.filter(
        status=Request.Status.PENDING
    ).count()

    in_progress_requests = Request.objects.filter(
        status=Request.Status.IN_PROGRESS
    ).count()

    resolved_requests = Request.objects.filter(
        status__in=[
            Request.Status.RESOLVED,
            Request.Status.CLOSED,
        ]
    ).count()

    recent_requests = (
        Request.objects
        .select_related(
            "student",
            "department",
            "category",
            "assigned_staff",
        )
        .order_by("-created_at")[:10]
    )

    return render(
        request,
        "admin_panel/dashboard.html",
        {
            "dashboard_type": "admin",
            "title": "Admin Dashboard",

            "total_students": total_students,
            "total_staff": total_staff,
            "total_requests": total_requests,
            "total_attendance": total_attendance,

            "pending_requests": pending_requests,
            "in_progress_requests": in_progress_requests,
            "resolved_requests": resolved_requests,

            "recent_requests": recent_requests,
        }
    )


@login_required
def department_students(request):
    user = request.user

    if user.role != User.Roles.STAFF:
        return redirect("dashboard:dashboard")

    # Get the staff member's department from StaffProfile first.
    staff_profile = getattr(user, "staff_profile", None)
    department = (
        staff_profile.department
        if staff_profile and staff_profile.department_id
        else user.department
    )

    query = request.GET.get("q", "").strip()

    if department:
        students = User.objects.filter(
            role=User.Roles.STUDENT,
            department=department,
            is_active=True,
        ).select_related("department").order_by(
            "first_name", "last_name", "username"
        )
    else:
        students = User.objects.none()

    if query:
        students = students.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(username__icontains=query)
            | Q(email__icontains=query)
        )

    return render(
        request,
        "dashboard/department_students.html",
        {
            "students": students,
            "department": department,
            "query": query,
        },
    )


@login_required
def department_staff(request):
    user = request.user

    if user.role != User.Roles.STUDENT:
        return redirect("dashboard:dashboard")

    department = user.department

    if department:
        # Staff department is stored in StaffProfile.department.
        staff_members = User.objects.filter(
            role=User.Roles.STAFF,
            is_active=True,
            staff_profile__department=department,
        ).select_related(
            "department", "staff_profile", "staff_profile__department"
        ).order_by(
            "first_name", "last_name", "username"
        )
    else:
        staff_members = User.objects.none()

    return render(
        request,
        "dashboard/department_staff.html",
        {
            "staff_members": staff_members,
            "department": department,
        },
    )

@login_required
def student_list(request):
    if request.user.role != User.Roles.ADMIN:
        return redirect("dashboard:dashboard")

    students = User.objects.filter(
        role=User.Roles.STUDENT
    ).select_related("department").order_by("-created_at")

    query = request.GET.get("q", "").strip()
    if query:
        students = students.filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
        )

    
    return render(
    request,
    "admin_panel/students.html",
    {
        "students": students,
        "search": query,
        "query": query,
    },
)


@login_required
def student_create(request):
    if request.user.role != User.Roles.ADMIN:
        return redirect("dashboard:dashboard")

    departments = Department.objects.filter(is_active=True)

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password", "")
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        phone = request.POST.get("phone", "").strip()
        department_id = request.POST.get("department", "")

        if not all([username, email, password]):
            messages.error(
                request,
                "Username, email, and password are required.",
            )
        elif User.objects.filter(username__iexact=username).exists():
            messages.error(request, "That username is already in use.")
        elif User.objects.filter(email__iexact=email).exists():
            messages.error(request, "That email address is already in use.")
        else:
            department = None

            if department_id:
                department = get_object_or_404(
                    Department,
                    pk=department_id,
                    is_active=True,
                )

            student = User(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
                phone=phone,
                department=department,
                role=User.Roles.STUDENT,
            )

            student.set_password(password)

            if request.FILES.get("profile_photo"):
                student.profile_photo = request.FILES["profile_photo"]

            student.save()
            messages.success(request, "Student account created successfully.")
            return redirect("dashboard:student_list")

    return render(
        request,
        "admin_panel/students/form.html",
        {"departments": departments, "student": None, "page_title": "Create Student"},
    )


@login_required
def student_detail(request, student_id):
    if request.user.role != User.Roles.ADMIN:
        return redirect("dashboard:dashboard")

    student = get_object_or_404(
        User.objects.select_related("department"),
        pk=student_id,
        role=User.Roles.STUDENT,
    )

    return render(
        request,
        "admin_panel/students/detail.html",
        {
            "student": student,
            "title": "Student Profile",
        },
    )




@login_required
def student_edit(request, student_id):
    if request.user.role != User.Roles.ADMIN:
        return redirect("dashboard:dashboard")

    student = get_object_or_404(
        User,
        pk=student_id,
        role=User.Roles.STUDENT,
    )
    departments = Department.objects.filter(is_active=True)

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip().lower()
        department_id = request.POST.get("department", "")

        if not username or not email:
            messages.error(request, "Username and email are required.")
        elif User.objects.filter(
            username__iexact=username
        ).exclude(pk=student.pk).exists():
            messages.error(request, "That username is already in use.")
        elif User.objects.filter(
            email__iexact=email
        ).exclude(pk=student.pk).exists():
            messages.error(request, "That email address is already in use.")
        else:
            student.username = username
            student.email = email
            student.first_name = request.POST.get("first_name", "").strip()
            student.last_name = request.POST.get("last_name", "").strip()
            student.phone = request.POST.get("phone", "").strip()

            student.department = (
                get_object_or_404(
                    Department,
                    pk=department_id,
                    is_active=True,
                )
                if department_id
                else None
            )

            if request.POST.get("password"):
                student.set_password(request.POST["password"])

            if request.FILES.get("profile_photo"):
                student.profile_photo = request.FILES["profile_photo"]

            student.save()
            messages.success(request, "Student details updated successfully.")
            return redirect("dashboard:student_list")

    return render(
        request,
        "admin_panel/students/form.html",
        {
            "departments": departments,
            "student": student,
            "page_title": "Edit Student",
        },
    )


@login_required
@require_POST
def student_delete(request, student_id):
    if request.user.role != User.Roles.ADMIN:
        return redirect("dashboard:dashboard")

    student = get_object_or_404(
        User,
        pk=student_id,
        role=User.Roles.STUDENT,
    )

    student.delete()
    messages.success(request, "Student account deleted successfully.")
    return redirect("dashboard:student_list")



