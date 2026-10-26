
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from helpdesk.models import Department

User = get_user_model()


class PasswordResetRequestForm(forms.Form):
    email = forms.EmailField(
        label="Account email",
        widget=forms.EmailInput(attrs={
            "class": "auth-input",
            "placeholder": "you@example.com",
            "autocomplete": "email",
            "autofocus": True,
        }),
    )


class StudentRegistrationForm(UserCreationForm):
    first_name = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "First Name",
        }),
    )

    last_name = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Last Name",
        }),
    )

    username = forms.CharField(
        max_length=150,
        required=True,
        label="Student ID / Enrollment Number",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Enter Student ID",
        }),
    )

    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            "class": "form-control",
            "placeholder": "College Email",
        }),
    )

    phone = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Phone Number",
        }),
    )

    department = forms.ModelChoiceField(
        queryset=Department.objects.none(),
        required=True,
        empty_label="Select your department",
        widget=forms.Select(attrs={
            "class": "form-control",
        }),
    )

    password1 = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "placeholder": "Create Password",
        }),
    )

    password2 = forms.CharField(
        label="Confirm Password",
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "placeholder": "Confirm Password",
        }),
    )

    class Meta:
        model = User
        fields = [
            "first_name",
            "last_name",
            "username",
            "email",
            "phone",
            "department",
            "password1",
            "password2",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = Department.objects.filter(
            is_active=True
        ).order_by("name")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()

        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "An account with this email already exists."
            )

        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Roles.STUDENT
        user.department = self.cleaned_data["department"]

        if commit:
            user.save()

        return user



class StudentProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = [
            "first_name",
            "last_name",
            "email",
            "phone",
            "department",
            "profile_photo",
        ]

        widgets = {
            "first_name": forms.TextInput(attrs={
                "class": "profile-input",
                "placeholder": "Enter first name",
            }),
            "last_name": forms.TextInput(attrs={
                "class": "profile-input",
                "placeholder": "Enter last name",
            }),
            "email": forms.EmailInput(attrs={
                "class": "profile-input",
                "placeholder": "Enter email address",
            }),
            "phone": forms.TextInput(attrs={
                "class": "profile-input",
                "placeholder": "Enter phone number",
            }),
            "department": forms.Select(attrs={
                "class": "profile-input",
            }),
            "profile_photo": forms.ClearableFileInput(attrs={
                "class": "profile-file-input",
                "accept": "image/*",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["department"].queryset = Department.objects.filter(
            is_active=True
        ).order_by("name")
        self.fields["department"].required = True
        self.fields["profile_photo"].required = False

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()

        if User.objects.filter(
            email__iexact=email
        ).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(
                "This email address is already in use."
            )

        return email

    def clean_profile_photo(self):
        photo = self.cleaned_data.get("profile_photo")

        if photo and hasattr(photo, "content_type"):
            if photo.content_type not in (
                "image/jpeg",
                "image/png",
                "image/webp",
            ):
                raise forms.ValidationError(
                    "Choose a JPG, PNG, or WebP image."
                )

            if photo.size > 5 * 1024 * 1024:
                raise forms.ValidationError(
                    "The image must be 5 MB or smaller."
                )

        return photo
