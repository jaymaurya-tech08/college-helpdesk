import secrets
import logging
import cv2
import numpy as np
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import EmailMultiAlternatives
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from helpdesk.models import Department
from attendance.face_service import get_face_embeddings_from_image
from attendance.models import StudentFace
from .forms import (
    PasswordResetRequestForm,
    StudentRegistrationForm,
    StudentProfileForm,
)


User = get_user_model()

OTP_SESSION_KEY = "registration_otp"
PENDING_USER_KEY = "pending_student_registration"
OTP_EXPIRY_MINUTES = 5
MAX_OTP_ATTEMPTS = 5
PASSWORD_RESET_EMAIL_KEY = "password_reset_email"
PASSWORD_RESET_OTP_KEY = "password_reset_otp"
PASSWORD_RESET_VERIFIED_KEY = "password_reset_verified_until"
PASSWORD_RESET_LAST_SENT_KEY = "password_reset_last_sent"
PASSWORD_RESET_RESEND_SECONDS = 30
PASSWORD_RESET_WINDOW_MINUTES = 5

logger = logging.getLogger(__name__)


def _clear_password_reset_session(request):
    for key in (
        PASSWORD_RESET_EMAIL_KEY,
        PASSWORD_RESET_OTP_KEY,
        PASSWORD_RESET_VERIFIED_KEY,
        PASSWORD_RESET_LAST_SENT_KEY,
    ):
        request.session.pop(key, None)


def _send_password_reset_otp(request, user):
    """Create and email a short-lived OTP for an existing account."""
    otp = f"{secrets.randbelow(1_000_000):06d}"
    request.session[PASSWORD_RESET_OTP_KEY] = {
        "hash": make_password(otp),
        "expires_at": (
            timezone.now() + timedelta(minutes=OTP_EXPIRY_MINUTES)
        ).isoformat(),
        "attempts": 0,
    }
    request.session[PASSWORD_RESET_LAST_SENT_KEY] = timezone.now().isoformat()

    first_name = user.first_name or user.username
    context = {
        "first_name": first_name,
        "otp": otp,
        "expiry_minutes": OTP_EXPIRY_MINUTES,
    }
    html_message = render_to_string(
        "emails/password_reset_otp.html",
        context,
    )
    email_message = EmailMultiAlternatives(
        subject="Your College Help Desk password reset code",
        body=(
            f"Hello {first_name}, your password reset code is {otp}. "
            f"It expires in {OTP_EXPIRY_MINUTES} minutes."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    email_message.attach_alternative(html_message, "text/html")
    email_message.send(fail_silently=False)
    request.session.modified = True


def password_reset_request(request):
    if request.user.is_authenticated:
        return redirect("dashboard:dashboard")

    form = PasswordResetRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        previous_email = request.session.get(PASSWORD_RESET_EMAIL_KEY)
        previous_sent_at = request.session.get(PASSWORD_RESET_LAST_SENT_KEY)
        _clear_password_reset_session(request)
        email = form.cleaned_data["email"].strip().lower()
        request.session[PASSWORD_RESET_EMAIL_KEY] = email

        resend_limited = False
        if previous_email == email and previous_sent_at:
            sent_at = datetime.fromisoformat(previous_sent_at)
            resend_limited = (
                (timezone.now() - sent_at).total_seconds()
                < PASSWORD_RESET_RESEND_SECONDS
            )

        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user and not resend_limited:
            try:
                _send_password_reset_otp(request, user)
            except Exception:
                logger.exception("Unable to send password reset OTP")
                request.session.pop(PASSWORD_RESET_OTP_KEY, None)
                request.session.pop(PASSWORD_RESET_LAST_SENT_KEY, None)

        request.session.modified = True
        messages.info(
            request,
            "If an active account uses that email, a verification code has been sent.",
        )
        return redirect("accounts:password_reset_verify")

    return render(
        request,
        "accounts/password_reset_request.html",
        {"form": form},
    )


def password_reset_verify(request):
    email = request.session.get(PASSWORD_RESET_EMAIL_KEY)
    if not email:
        messages.error(request, "Start by entering your account email.")
        return redirect("accounts:password_reset")

    if request.method == "POST" and request.POST.get("action") == "resend":
        last_sent = request.session.get(PASSWORD_RESET_LAST_SENT_KEY)
        if last_sent:
            sent_at = datetime.fromisoformat(last_sent)
            elapsed = (timezone.now() - sent_at).total_seconds()
            if elapsed < PASSWORD_RESET_RESEND_SECONDS:
                messages.warning(
                    request,
                    "Please wait a little before requesting another code.",
                )
                return redirect("accounts:password_reset_verify")

        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user:
            try:
                request.session.pop(PASSWORD_RESET_OTP_KEY, None)
                _send_password_reset_otp(request, user)
            except Exception:
                logger.exception("Unable to resend password reset OTP")
                request.session.pop(PASSWORD_RESET_OTP_KEY, None)
                request.session.pop(PASSWORD_RESET_LAST_SENT_KEY, None)

        messages.info(
            request,
            "If an active account uses that email, a new code has been sent.",
        )
        return redirect("accounts:password_reset_verify")

    if request.method == "POST":
        otp_data = request.session.get(PASSWORD_RESET_OTP_KEY)
        otp = request.POST.get("otp", "").strip()
        expiry = (
            datetime.fromisoformat(otp_data["expires_at"])
            if otp_data and otp_data.get("expires_at")
            else None
        )

        if otp_data is None:
            messages.error(
                request,
                "That code is invalid or expired. Request a new code and try again.",
            )
        elif expiry is None or timezone.now() >= expiry:
            request.session.pop(PASSWORD_RESET_OTP_KEY, None)
            messages.error(request, "That code has expired. Request a new one.")
        elif otp_data.get("attempts", 0) >= MAX_OTP_ATTEMPTS:
            request.session.pop(PASSWORD_RESET_OTP_KEY, None)
            messages.error(
                request,
                "Too many incorrect attempts. Request a new code.",
            )
        elif (
            len(otp) != 6
            or not otp.isdigit()
            or not check_password(otp, otp_data["hash"])
        ):
            otp_data["attempts"] += 1
            request.session[PASSWORD_RESET_OTP_KEY] = otp_data
            messages.error(request, "That code is incorrect. Please try again.")
        else:
            request.session[PASSWORD_RESET_VERIFIED_KEY] = (
                timezone.now() + timedelta(minutes=PASSWORD_RESET_WINDOW_MINUTES)
            ).isoformat()
            request.session.pop(PASSWORD_RESET_OTP_KEY, None)
            return redirect("accounts:password_reset_confirm")

        request.session.modified = True

    return render(
        request,
        "accounts/password_reset_verify.html",
        {"email": email},
    )


def password_reset_confirm(request):
    email = request.session.get(PASSWORD_RESET_EMAIL_KEY)
    verified_until = request.session.get(PASSWORD_RESET_VERIFIED_KEY)
    expires = datetime.fromisoformat(verified_until) if verified_until else None

    if not email or expires is None or timezone.now() >= expires:
        _clear_password_reset_session(request)
        messages.error(request, "Verify your email again to reset your password.")
        return redirect("accounts:password_reset")

    user = User.objects.filter(email__iexact=email, is_active=True).first()
    if user is None:
        _clear_password_reset_session(request)
        messages.error(request, "That account is no longer available.")
        return redirect("accounts:password_reset")

    form = SetPasswordForm(user, request.POST or None)
    for field in form.fields.values():
        field.widget.attrs["class"] = "auth-input"
    if request.method == "POST" and form.is_valid():
        form.save()
        _clear_password_reset_session(request)
        messages.success(request, "Your password was changed. You can now sign in.")
        return redirect("accounts:login")

    return render(
        request,
        "accounts/password_reset_confirm.html",
        {"form": form},
    )


def _send_registration_otp(request, email, first_name):
    """Generate a fresh OTP and send the branded HTML email."""
    otp = f"{secrets.randbelow(1_000_000):06d}"

    request.session[OTP_SESSION_KEY] = {
        "hash": make_password(otp),
        "expires_at": (
            timezone.now() + timedelta(minutes=OTP_EXPIRY_MINUTES)
        ).isoformat(),
        "attempts": 0,
    }

    context = {
        "first_name": first_name,
        "otp": otp,
        "expiry_minutes": OTP_EXPIRY_MINUTES,
    }

    html_message = render_to_string(
        "emails/registration_otp.html",
        context,
    )

    email_message = EmailMultiAlternatives(
        subject="Your College Help Desk verification code",
        body=(
            f"Hello {first_name}, your verification code is {otp}. "
            f"It expires in {OTP_EXPIRY_MINUTES} minutes."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[email],
    )
    email_message.attach_alternative(html_message, "text/html")
    email_message.send(fail_silently=False)


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard:dashboard")

    if request.method == "POST":
        form = StudentRegistrationForm(request.POST)

        if form.is_valid():
            face_files = request.FILES.getlist("face_photos")
            camera_photo = request.FILES.get("camera_face_photo")
            if camera_photo:
                face_files.append(camera_photo)

            if len(face_files) > 5:
                form.add_error(None, "Add no more than five face photos.")
            elif any(photo.size > 5 * 1024 * 1024 for photo in face_files):
                form.add_error(None, "Each face photo must be 5 MB or smaller.")
            elif any(photo.content_type not in ("image/jpeg", "image/png", "image/webp") for photo in face_files):
                form.add_error(None, "Face photos must be JPG, PNG, or WebP images.")
            else:
                face_embeddings = []
                try:
                    for photo in face_files:
                        image = cv2.imdecode(
                            np.frombuffer(photo.read(), dtype=np.uint8),
                            cv2.IMREAD_COLOR,
                        )
                        found = get_face_embeddings_from_image(image)
                        if len(found) != 1:
                            raise ValueError(
                                "Each photo must clearly show exactly one face. Try another photo or skip this step and ask staff to register it later."
                            )
                        face_embeddings.append(found[0].tolist())
                except ValueError as error:
                    form.add_error(None, str(error))
                except Exception:
                    logger.exception("Student signup face photo processing failed")
                    form.add_error(None, "We couldn't process that face photo. Try a clear JPG/PNG photo or skip this step and ask staff to register it later.")

            if not form.errors:
            # Hash the password without creating the account yet.
                user = form.save(commit=False)

                request.session[PENDING_USER_KEY] = {
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "username": user.username,
                    "email": user.email,
                    "phone": user.phone,
                    "password": user.password,
                    "department": user.department_id,
                    "role": User.Roles.STUDENT,
                    "face_embeddings": face_embeddings,
                }

                try:
                    _send_registration_otp(
                        request,
                        user.email,
                        user.first_name,
                    )
                except Exception:
                    request.session.pop(PENDING_USER_KEY, None)
                    request.session.pop(OTP_SESSION_KEY, None)
                    form.add_error(
                        None,
                        "We couldn't send the verification email. "
                        "Please check your email settings and try again.",
                    )
                else:
                    request.session.modified = True
                    return redirect("accounts:verify_email")

    else:
        form = StudentRegistrationForm()

    return render(
        request,
        "accounts/register.html",
        {"form": form},
    )



def verify_email(request):
    pending = request.session.get(PENDING_USER_KEY)
    otp_data = request.session.get(OTP_SESSION_KEY)

    if not pending or not otp_data:
        messages.error(
            request,
            "Your verification session has expired. Please register again.",
        )
        return redirect("accounts:register")

    if request.method == "POST":

        # Resend OTP
        if request.POST.get("action") == "resend":
            try:
                _send_registration_otp(
                    request,
                    pending["email"],
                    pending["first_name"],
                )
            except Exception:
                messages.error(
                    request,
                    "We couldn't send a new code. Please try again.",
                )
            else:
                messages.success(
                    request,
                    "A new verification code was sent.",
                )

            return redirect("accounts:verify_email")

        # Validate OTP
        otp = request.POST.get("otp", "").strip()
        otp_data = request.session.get(OTP_SESSION_KEY, {})

        expiry = (
            datetime.fromisoformat(otp_data["expires_at"])
            if otp_data.get("expires_at")
            else None
        )

        if expiry is None or timezone.now() >= expiry:
            request.session.pop(OTP_SESSION_KEY, None)
            messages.error(
                request,
                "Your code has expired. Request a new code below.",
            )
            return render(
                request,
                "accounts/verify_email.html",
                {"email": pending["email"]},
            )

        # Limit incorrect attempts
        attempts = otp_data.get("attempts", 0)

        if attempts >= MAX_OTP_ATTEMPTS:
            request.session.pop(OTP_SESSION_KEY, None)
            messages.error(
                request,
                "Too many incorrect attempts. Request a new code.",
            )
            return render(
                request,
                "accounts/verify_email.html",
                {"email": pending["email"]},
            )

        # Check OTP
        if (
            len(otp) != 6
            or not otp.isdigit()
            or not check_password(otp, otp_data["hash"])
        ):
            otp_data["attempts"] = attempts + 1
            request.session[OTP_SESSION_KEY] = otp_data
            request.session.modified = True

            messages.error(
                request,
                "That code is incorrect. Please try again.",
            )
            return render(
                request,
                "accounts/verify_email.html",
                {"email": pending["email"]},
            )

        # Check username uniqueness
        if User.objects.filter(
            username=pending["username"]
        ).exists():
            messages.error(
                request,
                "That student ID is already registered. Please log in.",
            )
            request.session.pop(PENDING_USER_KEY, None)
            request.session.pop(OTP_SESSION_KEY, None)
            return redirect("accounts:login")

        # Check email uniqueness
        if User.objects.filter(
            email__iexact=pending["email"]
        ).exists():
            messages.error(
                request,
                "That email is already registered. Please log in.",
            )
            request.session.pop(PENDING_USER_KEY, None)
            request.session.pop(OTP_SESSION_KEY, None)
            return redirect("accounts:login")

        # Get the selected active department
        department = Department.objects.filter(
            pk=pending.get("department"),
            is_active=True,
        ).first()

        if department is None:
            request.session.pop(PENDING_USER_KEY, None)
            request.session.pop(OTP_SESSION_KEY, None)

            messages.error(
                request,
                "The selected department is unavailable. Please register again.",
            )
            return redirect("accounts:register")

        # Create the student account
        user = User(
            first_name=pending["first_name"],
            last_name=pending["last_name"],
            username=pending["username"],
            email=pending["email"],
            phone=pending.get("phone", ""),
            department=department,
            role=User.Roles.STUDENT,
            password=pending["password"],
        )
        user.save()

        face_embeddings = pending.get("face_embeddings") or []
        if face_embeddings:
            StudentFace.objects.update_or_create(
                student=user,
                defaults={"embeddings": face_embeddings, "is_active": True},
            )

        # Clear verification session
        request.session.pop(PENDING_USER_KEY, None)
        request.session.pop(OTP_SESSION_KEY, None)

        # Log in the verified student
        login(request, user)

        messages.success(
            request,
            "Email verified! Your account is ready.",
        )

        return redirect("dashboard:dashboard")

    return render(
        request,
        "accounts/verify_email.html",
        {"email": pending["email"]},
    )


@login_required
def profile(request):
    if request.user.role != User.Roles.STUDENT:
        messages.error(request, "This page is for student accounts only.")
        return redirect("dashboard:dashboard")

    return render(
        request,
        "accounts/profile.html",
        {"profile_user": request.user},
    )



@login_required
def edit_profile(request):
    if request.user.role != User.Roles.STUDENT:
        messages.error(
            request,
            "This page is for student accounts only.",
        )
        return redirect("dashboard:dashboard")

    if request.method == "POST":
        form = StudentProfileForm(
            request.POST,
            request.FILES,
            instance=request.user,
        )

        if form.is_valid():
            form.save()
            messages.success(
                request,
                "Your profile was updated successfully.",
            )
            return redirect("accounts:profile")
    else:
        form = StudentProfileForm(instance=request.user)

    return render(
        request,
        "accounts/edit_profile.html",
        {"form": form},
    )
