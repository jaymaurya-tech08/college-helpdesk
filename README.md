# College Helpdesk

A Django-based college helpdesk and service portal for managing student requests, staff responses, department information, FAQs, and announcements.

This project is designed to streamline communication between students and college staff/admins by allowing students to raise issues, track their status, and receive updates while giving staff/admins tools to resolve, assign, and manage requests efficiently.

## Features

- Student request submission and tracking
- Staff dashboard for managing assigned requests
- Admin panel for managing:
  - students
  - staff members
  - departments
  - categories
  - FAQs
  - announcements
- Department directory and faculty information
- Request messaging system
- Feedback submission for completed requests
- Cloudinary-based media support
- Role-based access using Django authentication
- Responsive front-end templates

## Tech Stack

- Python
- Django 6.0
- PostgreSQL (via DATABASE_URL)
- HTML/CSS/JavaScript
- Cloudinary
- Whitenoise
- Python-dotenv

## Project Structure

```bash
college-helpdesk/
├── accounts/              # User accounts and authentication
├── config/                # Django settings, URLs, and app config
├── dashboard/             # Dashboard app
├── helpdesk/              # Core helpdesk functionality
├── static/                # Static files
├── templates/             # Shared HTML templates
├── .gitignore
├── manage.py
├── requirements.txt
├── .env.example          # Optional example env file
└── README.md
```

## Getting Started

### Prerequisites

- Python 3.10+
- pip
- PostgreSQL (recommended for production)
- Virtual environment tool

### 1. Clone the repository

```bash
git clone https://github.com/jaymaurya-tech08/college-helpdesk.git
cd college-helpdesk
```

### 2. Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
```

On Windows:

```bash
python -m venv .venv
.venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project root with the following:

```env
SECRET_KEY=your-secret-key
DEBUG=True
ALLOWED_HOSTS=127.0.0.1,localhost
DATABASE_URL=postgres://username:password@localhost:5432/college_helpdesk
TIME_ZONE=Asia/Kolkata

EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-email-password
DEFAULT_FROM_EMAIL=your-email@gmail.com

CLOUDINARY_CLOUD_NAME=your-cloud-name
CLOUDINARY_API_KEY=your-api-key
CLOUDINARY_API_SECRET=your-api-secret
```

> Note: If `DATABASE_URL` is not set, the app may not connect to a database correctly. For local development, PostgreSQL is strongly recommended.

### 5. Run database migrations

```bash
python manage.py migrate
```

### 6. Start the development server

```bash
python manage.py runserver
```

Then open:

```bash
http://127.0.0.1:8000/
```

## Default Roles

This project supports role-based flows for:

- Students
- Staff
- Admins

The app routes include pages for:
- student requests
- staff dashboard
- admin panel
- announcements
- FAQs
- department directory

## Admin Panel

You can access the Django admin interface at:

```bash
http://127.0.0.1:8000/admin/
```

## Contributing

Contributions are welcome.

### Recommended workflow

```bash
git checkout -b feature/your-feature-name
# make your changes
git add .
git commit -m "Add your feature"
git push origin feature/your-feature-name
```

Then open a pull request on GitHub.

## License

This project does not currently include a LICENSE file, so licensing terms are not specified yet. If you plan to distribute or use this project publicly, consider adding an appropriate open-source license.

## Notes

This repository appears to be a practical academic or college management project and is structured as a Django multi-role portal for helpdesk operations. It includes support for request management, departments, announcements, and FAQs.

If you want, I can also generate:
- a more polished GitHub-ready README
- a README with badges and screenshots section
- a README in Hindi/English bilingual format
- a .env.example file for this project
