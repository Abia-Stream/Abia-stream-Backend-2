# Abia Stream Backend

A Django REST Framework backend for the Abia Stream video streaming platform. Built with JWT authentication, Supabase PostgreSQL, and Cloudinary for media storage.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | Django 6.0 + Django REST Framework |
| Authentication | JWT via `djangorestframework-simplejwt` |
| Database | Supabase PostgreSQL (`psycopg2`) |
| Media Storage | Cloudinary |
| Email | SMTP (Gmail / SendGrid) |
| API Docs | drf-spectacular (OpenAPI 3) |
| Environment | python-decouple |

---

## Project Structure

```
Abia-Stream-Backend/
├── abiastream/
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── accounts/
│   ├── models.py          # Custom User model (managed=False)
│   ├── serializers.py
│   ├── views.py
│   ├── urls.py
│   ├── utils.py           # OTP generation, hashing, token helpers
│   ├── email_service.py   # Email sending logic
│   └── routers.py         # Supabase migration router
├── profiles/
│   ├── models.py          # Profile model (managed=False)
│   └── ...
├── .env
├── manage.py
└── requirements.txt
```

---

## Prerequisites

- Python 3.10+
- A [Supabase](https://supabase.com) project with the schema already created
- A Gmail account with an [App Password](https://myaccount.google.com/apppasswords) (for email)

---

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/your-username/abia-stream-backend.git
cd abia-stream-backend
```

### 2. Create and activate a virtual environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Create a `.env` file

```env
# Django
SECRET_KEY=your-django-secret-key
DEBUG=True
ALLOWED_HOSTS=127.0.0.1,localhost

# Database (Supabase)
DB_NAME=postgres
DB_USER=postgres
DB_PASSWORD=your-supabase-password
DB_HOST=db.xxxxxxxxxxxx.supabase.co
DB_PORT=5432

# Email (Gmail SMTP)
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=yourgmail@gmail.com
EMAIL_HOST_PASSWORD=your-16-char-app-password
DEFAULT_FROM_EMAIL=Abia Stream <yourgmail@gmail.com>
```

### 5. Run migrations

```bash
python manage.py migrate
```

> The custom `SupabaseRouter` prevents Django from creating `auth_*` and `django_content_type` tables in your Supabase database. Only Django's internal migration tracking tables are created.

### 6. Start the development server

```bash
python manage.py runserver
```

Server runs at `http://127.0.0.1:8000`

---

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `SECRET_KEY` | Django secret key | ✅ |
| `DEBUG` | `True` for development, `False` for production | ✅ |
| `ALLOWED_HOSTS` | Comma-separated list of allowed hosts | ✅ |
| `DB_NAME` | Supabase database name | ✅ |
| `DB_USER` | Supabase database user | ✅ |
| `DB_PASSWORD` | Supabase database password | ✅ |
| `DB_HOST` | Supabase database host | ✅ |
| `DB_PORT` | Supabase database port (default: 5432) | ✅ |
| `EMAIL_HOST` | SMTP host | ✅ |
| `EMAIL_PORT` | SMTP port (default: 587) | ✅ |
| `EMAIL_HOST_USER` | SMTP username / email address | ✅ |
| `EMAIL_HOST_PASSWORD` | SMTP password or app password | ✅ |
| `DEFAULT_FROM_EMAIL` | Sender name and email | ✅ |

---

## API Endpoints

### Authentication

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/api/auth/register/` | Register a new user | Public |
| `POST` | `/api/auth/verify-email/` | Verify email with OTP | Public |
| `POST` | `/api/auth/resend-otp/` | Resend verification OTP | Public |
| `POST` | `/api/auth/login/` | Login and get tokens | Public |
| `POST` | `/api/auth/token/refresh/` | Refresh access token | Public |
| `POST` | `/api/auth/logout/` | Logout and blacklist token | 🔒 |


### Password Reset

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/api/auth/forgot-password/` | Request password reset OTP | Public |
| `POST` | `/api/auth/verify-reset-otp/` | Verify reset OTP | Public |
| `POST` | `/api/auth/reset-password/` | Set new password | Public |

> Full request/response details are in [API_DOCUMENTATION.md](./API_DOCUMENTATION.md)

---

## Authentication Flow

```
1. POST /api/auth/register/         → account created (status: pending_verification)
2. POST /api/auth/verify-email/     → status promoted to active
3. POST /api/auth/login/            → returns access + refresh tokens
4. POST /api/auth/token/refresh/    → returns new access token (every 30 mins)
5. POST /api/auth/logout/           → blacklists refresh token
```

### Using the Access Token

Include it in the `Authorization` header for all protected endpoints:

```
Authorization: Bearer <access_token>
```

### Token Lifetimes

| Token | Lifetime |
|-------|----------|
| Access Token | 30 minutes |
| Refresh Token | 7 days |

---

## User Roles & Statuses

### Roles (`user_role`)

| Value | Description |
|-------|-------------|
| `viewer` | Default role for new users |
| `creator` | Can upload and manage videos |
| `moderator` | Can manage content |
| `admin` | Full access |

### Statuses (`user_status`)

| Value | Description |
|-------|-------------|
| `pending_verification` | Registered but email not verified |
| `active` | Verified and can log in |
| `suspended` | Temporarily restricted |
| `banned` | Permanently restricted |

---

## Security Features

- Passwords hashed with Django's PBKDF2 algorithm
- OTPs hashed with SHA-256 before storing in the database
- OTPs expire after **10 minutes**
- Account lockout after **5 failed login attempts** (locked for 15 minutes)
- Refresh token blacklisting on logout
- Email enumeration protection on resend OTP and forgot password endpoints

---

## Development Notes

### Testing emails locally

In development (`DEBUG=True`), emails are printed to the terminal instead of being sent:

```python
# settings.py
if DEBUG:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
```

The OTP will appear in your terminal output after calling `/api/auth/register/` or `/api/auth/resend-otp/`.

### Supabase migration router

The `SupabaseRouter` in `accounts/routers.py` blocks Django from running migrations for `auth`, `contenttypes`, `admin`, and `sessions` apps — keeping your Supabase schema clean.

```python
# accounts/routers.py
BLOCKED_APPS = {'admin', 'contenttypes', 'auth', 'sessions'}

class SupabaseRouter:
    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label in BLOCKED_APPS:
            return False
        return None
```

### `managed = False`

All models mapping to existing Supabase tables use `managed = False` in their `Meta` class — Django reads and writes to these tables but never creates, alters, or drops them.

---

## API Documentation

Interactive API docs are available at:

| Interface | URL |
|-----------|-----|
| Swagger UI | `http://127.0.0.1:8000/api/schema/swagger-ui/` |
| ReDoc | `http://127.0.0.1:8000/api/schema/redoc/` |
| OpenAPI Schema | `http://127.0.0.1:8000/api/schema/` |

---

## Postman Setup

1. Create a new environment called `Abia Stream - Dev`
2. Add variable `base_url` = `http://127.0.0.1:8000/api`
3. Add variables `access_token` and `refresh_token` (leave empty)
4. In the Login request **Tests** tab, add:

```javascript
if (pm.response.code === 200) {
    const res = pm.response.json();
    pm.environment.set("access_token", res.access);
    pm.environment.set("refresh_token", res.refresh);
}
```

5. Use `{{base_url}}/auth/login/` for all request URLs
6. Use `{{access_token}}` in the Bearer Token field for protected requests

---

## License

MIT