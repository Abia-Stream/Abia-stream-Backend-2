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
│   ├── serializers.py
│   ├── views.py
│   └── urls.py
├── videos/
├── playback/
│   ├── models.py          # WatchHistory, ViewLog (managed=False)
│   ├── serializers.py
│   ├── views.py
│   └── urls.py
│   ├── models.py          # Video, Category, Tag, VideoTag (managed=False)
│   ├── serializers.py
│   ├── views.py
│   ├── urls.py
│   └── cloudinary_service.py  # Cloudinary upload, thumbnail, signing
├── .env
├── manage.py
└── requirements.txt
```

---

## Prerequisites

- Python 3.10+
- A [Supabase](https://supabase.com) project with the schema already created
- A [Cloudinary](https://cloudinary.com) account with API keys
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

# Cloudinary
CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_api_secret
```

### 5. Run migrations

```bash
python manage.py migrate
```

### 6. Create a superuser (admin account)

```bash
python manage.py createsuperuser
```

### 7. Start the development server

```bash
python manage.py runserver
```

Server runs at `http://127.0.0.1:8000`

---

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `SECRET_KEY` | Django secret key | ✅ |
| `DEBUG` | `True` for dev, `False` for production | ✅ |
| `ALLOWED_HOSTS` | Comma-separated list of allowed hosts | ✅ |
| `DB_NAME` | Supabase database name | ✅ |
| `DB_USER` | Supabase database user | ✅ |
| `DB_PASSWORD` | Supabase database password | ✅ |
| `DB_HOST` | Supabase database host | ✅ |
| `DB_PORT` | Supabase database port (default: 5432) | ✅ |
| `EMAIL_HOST` | SMTP host | ✅ |
| `EMAIL_PORT` | SMTP port (default: 587) | ✅ |
| `EMAIL_HOST_USER` | SMTP email address | ✅ |
| `EMAIL_HOST_PASSWORD` | SMTP app password | ✅ |
| `DEFAULT_FROM_EMAIL` | Sender name and email | ✅ |
| `CLOUDINARY_CLOUD_NAME` | Cloudinary cloud name | ✅ |
| `CLOUDINARY_API_KEY` | Cloudinary API key | ✅ |
| `CLOUDINARY_API_SECRET` | Cloudinary API secret | ✅ |

---

## API Endpoints

### Authentication

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/api/auth/register/` | Register new user | Public |
| `POST` | `/api/auth/verify-email/` | Verify email OTP | Public |
| `POST` | `/api/auth/resend-otp/` | Resend verification OTP | Public |
| `POST` | `/api/auth/login/` | Login, get tokens | Public |
| `POST` | `/api/auth/logout/` | Logout, blacklist token | 🔒 |
| `POST` | `/api/auth/token/refresh/` | Refresh access token | Public |

### Password Reset

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/api/auth/forgot-password/` | Request reset OTP | Public |
| `POST` | `/api/auth/verify-reset-otp/` | Verify reset OTP | Public |
| `POST` | `/api/auth/reset-password/` | Set new password | Public |

### Profiles

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `GET` | `/api/profile/me/` | Get own profile | 🔒 |
| `PATCH` | `/api/profile/me/` | Update own profile | 🔒 |
| `GET` | `/api/profile/<user_id>/` | View public profile | Public |

### Videos

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/api/videos/upload/` | Server-side upload | 🔒 creator/admin |
| `GET` | `/api/videos/upload/signed-params/` | Client-side upload credentials | 🔒 creator/admin |
| `POST` | `/api/videos/upload/from-cloudinary/` | Save after client upload | 🔒 creator/admin |
| `GET` | `/api/videos/` | List public videos | Public |
| `GET` | `/api/videos/?category=1` | Filter by category | Public |
| `GET` | `/api/videos/?tag=1` | Filter by tag | Public |
| `GET` | `/api/videos/?creator=<uuid>` | Filter by creator | Public |
| `GET` | `/api/videos/me/` | My videos | 🔒 |
| `GET` | `/api/videos/me/?status=draft` | My drafts | 🔒 |
| `GET` | `/api/videos/<id>/` | Get single video | Public* |
| `PATCH` | `/api/videos/<id>/` | Update video | 🔒 Owner |
| `DELETE` | `/api/videos/<id>/` | Delete video | 🔒 Owner |
| `POST` | `/api/videos/<id>/publish/` | Publish video | 🔒 creator/admin |
| `POST` | `/api/videos/<id>/archive/` | Archive video | 🔒 creator/admin |

### Playback

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/api/playback/view/` | Record a view | Public |
| `POST` | `/api/playback/progress/` | Update watch progress | 🔒 |
| `GET` | `/api/playback/history/` | Get watch history | 🔒 |
| `DELETE` | `/api/playback/history/clear/` | Clear all history | 🔒 |
| `DELETE` | `/api/playback/history/<video_id>/` | Remove one video | 🔒 |
| `GET` | `/api/playback/continue-watching/` | Unfinished videos | 🔒 |

### Categories & Tags

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `GET` | `/api/categories/` | List active categories | Public |
| `GET` | `/api/tags/` | List tags by usage | Public |

> *Visibility rules apply for single video endpoint

> Full request/response details in [API_DOCUMENTATION.md](./API_DOCUMENTATION.md)

---

## Video Upload Flows

### Server-side (development / admin)
```
POST /api/videos/upload/
  File goes: Browser → Django → Cloudinary → Supabase DB
```

### Client-side (production / frontend)
```
1. GET  /api/videos/upload/signed-params/   → credentials
2. Frontend uploads directly to Cloudinary
3. POST /api/videos/upload/from-cloudinary/ → save metadata
  File goes: Browser → Cloudinary directly (Django not involved)
```

---

## Video Status Flow

```
Upload → processing → ready → published
                   ↘ failed
published → archived
any → blocked (admin only)
```

---

## User Roles & Permissions

| Role | Upload | Publish | Watch | Moderate | Admin |
|------|--------|---------|-------|----------|-------|
| `viewer` | ❌ | ❌ | ✅ | ❌ | ❌ |
| `creator` | ✅ | ✅ own | ✅ | ❌ | ❌ |
| `moderator` | ❌ | ❌ | ✅ | ✅ | ❌ |
| `admin` | ✅ | ✅ | ✅ | ✅ | ✅ |

---

## User Statuses

| Status | Description |
|--------|-------------|
| `pending_verification` | Registered, email not verified |
| `active` | Verified, can log in |
| `suspended` | Temporarily restricted |
| `banned` | Permanently restricted |

---

## Security Features

- Passwords hashed with Django's PBKDF2 algorithm
- OTPs hashed with SHA-256 before storing
- OTPs expire after **10 minutes**
- Account lockout after **5 failed login attempts** (15 minutes)
- Refresh token blacklisting on logout
- Email enumeration protection
- Cloudinary signed uploads (tamper-proof)
- Role-based upload restrictions
- Private/subscribers_only video access control

---

## Development Notes

### Testing emails locally

```python
# settings.py — emails print to terminal in DEBUG mode
if DEBUG:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
```

### Creating test accounts by role

Register via API then update role in Supabase SQL Editor:

```sql
UPDATE users SET role = 'creator' WHERE email = 'testcreator@example.com';
UPDATE users SET role = 'moderator' WHERE email = 'testmoderator@example.com';
```

### Video processing in development

After upload, videos start with status `processing`. Cloudinary processes them asynchronously. For testing, manually set to `ready` in Supabase:

```sql
UPDATE videos SET status = 'ready' WHERE id = 'your-video-uuid';
```

In production, a Cloudinary webhook will automatically update the status (Phase 4 — Celery).

### Supabase migration router

Blocks Django from creating `auth_*` and internal tables in Supabase:

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

All models use `managed = False` — Django reads/writes but never creates or alters tables.

---

## API Documentation

| Interface | URL |
|-----------|-----|
| Swagger UI | `http://127.0.0.1:8000/api/docs/ui` |
| OpenAPI Schema | `http://127.0.0.1:8000/api/docs/schema/` |

---

## Postman Setup

1. Environment: `Abia-Stream-Dev`
2. Variables: `base_url` = `http://127.0.0.1:8000/api`
3. Login **Scripts → Post-response**:

```javascript
if (pm.response.code === 200) {
    const res = pm.response.json();
    pm.environment.set("access_token", res.access);
    pm.environment.set("refresh_token", res.refresh);
}
```

4. Protected requests → Authorization → Bearer Token → `{{access_token}}`
5. Video upload → Body → **form-data**, `video_file` key type = **File**

---

## Roadmap

- [x] Phase 1 — Auth Service (register, login, OTP, password reset)
- [x] Phase 1 — Profile Service (CRUD)
- [x] Phase 1 — Content Service (video upload, CRUD, categories, tags)
- [x] Phase 1 — Playback Service (watch history, view logs)
- [ ] Phase 2 — Interactions (likes, saves, shares)
- [ ] Phase 2 — Creator Channels
- [ ] Phase 2 — Subscriptions
- [ ] Phase 2 — Notifications
- [ ] Phase 3 — Livestreams
- [ ] Phase 4 — Redis Cache
- [ ] Phase 4 — Search Service
- [ ] Phase 4 — Analytics
- [ ] Phase 4 — Cloudinary Webhooks (auto status update)
- [ ] Phase 5 — Docker + CI/CD + Production deployment

---

## License

MIT