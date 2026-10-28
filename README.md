# Abia Stream Backend

> **What changed:** [CHANGELOG.md](CHANGELOG.md) · **Frontend to-do:** [FRONTEND_INTEGRATION.md](FRONTEND_INTEGRATION.md) · **Endpoints:** [API DOCUMENTATION.md](API%20DOCUMENTATION.md)

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
├── channels/
├── interactions/
│   ├── models.py          # Interaction (managed=False)
│   ├── serializers.py
│   ├── views.py
│   ├── urls.py
│   └── file_security.py   # Upload security pipeline
├── subscriptions/
│   ├── models.py          # Subscription (managed=False)
│   ├── serializers.py
│   ├── views.py
│   ├── urls.py
│   └── notifications.py   # Subscription notifications
├── notifications/
│   ├── models.py          # Notification (managed=False)
│   ├── serializers.py
│   ├── views.py
│   └── urls.py
│   ├── models.py          # CreatorChannel (managed=False)
│   ├── serializers.py
│   ├── views.py
│   └── urls.py
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
| `REDIS_URL` | Redis for cache, websockets and Celery (default `redis://localhost:6379`) | ✅ in production |
| `CELERY_BROKER_URL` | Override the Celery broker (defaults to `REDIS_URL`) | ❌ |
| `CLOUDINARY_AUTH_TOKEN_KEY` | Cloudinary token-auth key; makes signed video URLs expire | ❌ |
| `SIGNED_URL_TTL_SECONDS` | Lifetime of expiring signed URLs (default 3600) | ❌ |
| `CLOUDINARY_WEBHOOK_VERIFY` | `off`, `log` (default) or `enforce` — Cloudinary webhook signature check | ❌ |
| `LIVESTREAM_IDLE_TIMEOUT_SECONDS` | How long a dropped encoder may reconnect before a stream ends (default 120) | ❌ |
| `LIVESTREAM_MAX_RUNTIME_SECONDS` | Maximum stream length (default 10800 = 3 h; Cloudinary's limit for recorded streams, larger values are capped) | ❌ |
| `PAYSTACK_SECRET_KEY` / `PAYSTACK_PUBLIC_KEY` | Paystack keys (test keys start `sk_test_` / `pk_test_`) | ✅ for payments |
| `PAYSTACK_CALLBACK_URL` | Frontend page Paystack returns viewers to after paying | ✅ for payments |
| `MODERATION_BANNED_TERMS` | Comma-separated words/phrases flagged in comments/videos and refused in chat | ❌ |

---

## Database Changes (`sql/`)

Every model is `managed = False`: the schema lives in Supabase and Django migrations never change it. Schema changes are numbered SQL scripts in `sql/`, applied **in order** in the Supabase SQL editor. Each one is idempotent (safe to re-run).

| Script | What it does |
|--------|--------------|
| `001_events.sql` | Behaviour event log |
| `002_video_search.sql` | Full-text search column + indexes |
| `003_recommendations.sql` | Related-videos table |
| `004_experiments.sql` | A/B testing tables |
| `005_view_logs_partitions.sql` | Monthly `view_logs` partitions for 2026 + a default partition (view recording fails without these) |
| `006_video_delivery_type.sql` | Tracks public vs signed-only Cloudinary storage per video |
| `007_moderation.sql` | Content reports + moderation audit log |
| `008_livestreaming.sql` | Livestream columns, viewer sessions, live chat, moderation actions for streams |
| `009_auto_moderation.sql` | Video fingerprints, `held` video status, automatic entries in the moderation queue |
| `010_personalization.sql` | Ranker models, "up next" transitions, `feed_ranker` and `search_personalization` experiments (created off) |
| `011_monetization.sql` | Tips, memberships, payouts, ad revenue share, earnings ledger, `members_only` visibility |

`sql/baseline/000_live_schema.sql` is a schema-only snapshot of production used **only** by the test suite. Never run it against Supabase.

---

## Background Workers (Celery)

Scheduled and background jobs run on Celery with Redis as the broker. The web process does not need them to be up — anything queued from a request is best-effort and has a catch-up command — but these should run in production:

```bash
celery -A abiastream worker -l info
celery -A abiastream beat -l info
```

| Schedule (UTC) | Task | Manual equivalent |
|----------------|------|-------------------|
| Daily 01:00 | Create upcoming `view_logs` monthly partitions | `python manage.py ensure_view_log_partitions` |
| Daily 03:00 | Rebuild "related videos" from watch history | `python manage.py build_related_videos --prune` |
| On visibility change | Move a video between public and signed-only storage | `python manage.py sync_video_delivery` (dry run; add `--apply`) |
| Every minute | Livestream status, recordings → videos, cleanup (also happens whenever a stream is viewed) | `python manage.py sync_livestreams` |
| Hourly (:20) | Fingerprint and check videos the upload-time checks missed | `python manage.py scan_videos` |
| Daily 03:30 | Rebuild "up next" from viewing sessions | `python manage.py build_video_transitions` |
| Daily 04:00 | Retrain the feed ranker; activates only if clearly better | `python manage.py train_feed_ranker` (`--dry-run` to just report) |

---

## Running Tests

Tests need a **local** PostgreSQL (they refuse to run against any other host) and never touch Cloudinary or Redis. The runner builds a throwaway `test_<name>` database from `sql/baseline/` plus every `sql/0*.sql`, so it also checks that each script applies cleanly on top of production's schema.

```bash
# TEST_DB_HOST / TEST_DB_PORT / TEST_DB_USER / TEST_DB_PASSWORD default to localhost:5432, postgres, no password
python manage.py test --settings=abiastream.test_settings
```

---


---

## API Versioning

All endpoints are prefixed with `/api/v1/`. Future breaking changes will be released under `/api/v2/` without removing v1.

```
Development: http://127.0.0.1:8000/api/v1
Production:  https://abia-stream-backend.onrender.com/api/v1
```

---

## Pagination

All list endpoints return **8 results per page** by default.

```
GET /api/v1/videos/           → page 1
GET /api/v1/videos/?page=2    → page 2
GET /api/v1/videos/?page_size=4 → 4 per page (max 50)
```

Response format:
```json
{
    "pagination": {
        "total": 24,
        "page": 1,
        "page_size": 8,
        "total_pages": 3,
        "next": "http://127.0.0.1:8000/api/v1/videos/?page=2",
        "previous": null
    },
    "results": [...]
}
```

---

## File Upload Security

All uploads go through a 10-step security pipeline in `videos/file_security.py`:

```
1.  Auth check
2.  File size (max 500MB video / 10MB image)
3.  Extension allowlist (.mp4 .mov .avi .mkv .webm)
4.  MIME type verification
5.  Magic bytes / file signature check
6.  Malicious pattern scan
7.  Safe UUID filename generated (original discarded)
8.  Stored on Cloudinary (never on server)
9.  DB saved via ORM (parameterized queries)
10. Served via signed Cloudinary URLs
```

## API Endpoints

### Authentication

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/api/v1/auth/register/` | Register new user | Public |
| `POST` | `/api/v1/auth/verify-email/` | Verify email OTP | Public |
| `POST` | `/api/v1/auth/resend-otp/` | Resend verification OTP | Public |
| `POST` | `/api/v1/auth/login/` | Login, get tokens | Public |
| `POST` | `/api/v1/auth/logout/` | Logout, blacklist token | 🔒 |
| `POST` | `/api/v1/auth/token/refresh/` | Refresh access token | Public |

### Password Reset

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/api/v1/auth/forgot-password/` | Request reset OTP | Public |
| `POST` | `/api/v1/auth/verify-reset-otp/` | Verify reset OTP | Public |
| `POST` | `/api/v1/auth/reset-password/` | Set new password | Public |

### Profiles

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `GET` | `/api/v1/profile/me/` | Get own profile | 🔒 |
| `PATCH` | `/api/v1/profile/me/` | Update own profile | 🔒 |
| `GET` | `/api/v1/profile/<user_id>/` | View public profile | Public |

### Videos

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/api/v1/videos/upload/` | Server-side upload | 🔒 creator/admin |
| `GET` | `/api/v1/videos/upload/signed-params/` | Client-side upload credentials | 🔒 creator/admin |
| `POST` | `/api/v1/videos/upload/from-cloudinary/` | Save after client upload | 🔒 creator/admin |
| `GET` | `/api/v1/videos/` | List public videos | Public |
| `GET` | `/api/v1/videos/?category=1` | Filter by category | Public |
| `GET` | `/api/v1/videos/?tag=1` | Filter by tag | Public |
| `GET` | `/api/v1/videos/?creator=<uuid>` | Filter by creator | Public |
| `GET` | `/api/v1/videos/me/` | My videos | 🔒 |
| `GET` | `/api/v1/videos/me/?status=draft` | My drafts | 🔒 |
| `GET` | `/api/v1/videos/<id>/` | Get single video | Public* |
| `PATCH` | `/api/v1/videos/<id>/` | Update video | 🔒 Owner |
| `DELETE` | `/api/v1/videos/<id>/` | Delete video | 🔒 Owner |
| `POST` | `/api/v1/videos/<id>/publish/` | Publish video | 🔒 creator/admin |
| `POST` | `/api/v1/videos/<id>/archive/` | Archive video | 🔒 creator/admin |

### Creator Channels

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `GET` | `/api/v1/channels/` | List all channels | Public |
| `POST` | `/api/v1/channels/create/` | Create channel | 🔒 |
| `GET` | `/api/v1/channels/me/` | Get my channel | 🔒 |
| `PATCH` | `/api/v1/channels/me/` | Update my channel | 🔒 |
| `DELETE` | `/api/v1/channels/me/delete/` | Delete my channel | 🔒 |
| `GET` | `/api/v1/channels/<slug>/` | Get public channel | Public |
| `GET` | `/api/v1/channels/<slug>/videos/` | Get channel videos | Public |

### Playback

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/api/v1/playback/view/` | Record a view | Public |
| `POST` | `/api/v1/playback/progress/` | Update watch progress | 🔒 |
| `GET` | `/api/v1/playback/history/` | Get watch history | 🔒 |
| `DELETE` | `/api/v1/playback/history/clear/` | Clear all history | 🔒 |
| `DELETE` | `/api/v1/playback/history/<video_id>/` | Remove one video | 🔒 |
| `GET` | `/api/v1/playback/continue-watching/` | Unfinished videos | 🔒 |


### Interactions

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/api/v1/interactions/` | Add/Remove interaction | 🔒 |
| `GET` | `/api/v1/interactions/video/<id>/status/` | My interaction status | 🔒 |
| `GET` | `/api/v1/interactions/video/<id>/counts/` | Video counts | Public |
| `GET` | `/api/v1/interactions/liked/` | My liked videos | 🔒 |
| `GET` | `/api/v1/interactions/saved/` | My saved videos | 🔒 |
| `GET` | `/api/v1/interactions/favourites/` | My favourited videos | 🔒 |

### Subscriptions

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/api/v1/subscriptions/<slug>/` | Subscribe/Unsubscribe | 🔒 |
| `GET` | `/api/v1/subscriptions/` | My subscriptions | 🔒 |
| `GET` | `/api/v1/subscriptions/<slug>/status/` | Subscription status | 🔒 |
| `GET` | `/api/v1/subscriptions/<slug>/subscribers/` | Channel subscribers | Public |


### Notifications

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `GET` | `/api/v1/notifications/` | List notifications | 🔒 |
| `GET` | `/api/v1/notifications/unread-count/` | Unread count | 🔒 |
| `PATCH` | `/api/v1/notifications/<id>/read/` | Mark as read | 🔒 |
| `PATCH` | `/api/v1/notifications/read-all/` | Mark all as read | 🔒 |
| `PATCH` | `/api/v1/notifications/<id>/archive/` | Archive | 🔒 |
| `DELETE` | `/api/v1/notifications/<id>/` | Delete | 🔒 |

### Categories & Tags

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `GET` | `/api/v1/categories/` | List active categories | Public |
| `GET` | `/api/v1/tags/` | List tags by usage | Public |

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
# Also includes: accounts, profiles, videos, playback, channels
BLOCKED_APPS = {'admin', 'contenttypes', 'auth', 'sessions'}

class SupabaseRouter:
    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label in BLOCKED_APPS:
            return False
        return None
```

### Email Service (Production)

Uses **Resend HTTP API** instead of SMTP — Render's free tier blocks SMTP port 587.

```python
# Production email
import resend
resend.api_key = settings.RESEND_API_KEY
```

Required Render environment variables:
```
RESEND_API_KEY=re_xxxxxxxxxxxxx
DEFAULT_FROM_EMAIL=onboarding@resend.dev
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
2. Variables: `base_url` = `http://127.0.0.1:8000/api/v1`
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
- [x] Phase 2 — Interactions (likes, saves, dislikes, saves, favourites, reports)
- [x] Phase 2 — Creator Channels
- [x] Phase 2 — Subscriptions (follow/unfollow creators)
- [x] Phase 2 — Notifications
- [ ] Phase 3 — Livestreams
- [ ] Phase 4 — Redis Cache
- [ ] Phase 4 — Search Service
- [ ] Phase 4 — Analytics
- [ ] Phase 4 — Cloudinary Webhooks (auto status update)
- [ ] Phase 5 — Docker + CI/CD + Production deployment

---

## License

MIT

---

## Creator Channel Role Flow

```
Register → role: viewer
      ↓
POST /api/channels/create/   → role promoted to creator
      ↓
Creator can now upload videos

DELETE /api/channels/me/delete/ → role demoted back to viewer
      ↓
Upload permissions removed
```

