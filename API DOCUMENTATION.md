# Abia Stream API Documentation

**Version:** 1.0.0  
**Base URL:** `http://127.0.0.1:8000/api/v1` (development) · `https://api.abiastream.com/api/v1` (production)  
**Authentication:** Bearer JWT Token

---

## Table of Contents

1. [Authentication](#authentication)
2. [Email Verification](#email-verification)
3. [Password Reset](#password-reset)
4. [Token Management](#token-management)
5. [Profiles](#profiles)
6. [Videos](#videos)
7. [Categories](#categories)
8. [Tags](#tags)
9. [Notifications](#notifications)
10. [Enums Reference](#enums-reference)
10. [Error Responses](#error-responses)
11. [Status Codes](#status-codes)


---

## API Versioning

All endpoints are versioned under `/api/v1/`. When breaking changes are introduced a new version `/api/v2/` will be released without removing `/api/v1/`.

```
Base URL (development): http://127.0.0.1:8000/api/v1
Base URL (production):  https://abia-stream-backend.onrender.com/api/v1
```

---

## Pagination

All list endpoints return paginated responses with **8 results per page**.

**Query Parameters**

| Param | Type | Description |
|-------|------|-------------|
| `page` | int | Page number (default: 1) |
| `page_size` | int | Results per page (max: 50, default: 8) |

**Paginated Response Format**
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

**Examples**
```
GET /api/v1/videos/           → page 1 (default)
GET /api/v1/videos/?page=2    → page 2
GET /api/v1/videos/?page_size=4  → 4 results per page
```

**Paginated endpoints:**
- `GET /api/v1/videos/` — public feed
- `GET /api/v1/videos/me/` — my videos
- `GET /api/v1/channels/` — channel list
- `GET /api/v1/channels/<slug>/videos/` — channel videos
- `GET /api/v1/playback/history/` — watch history
- `GET /api/v1/interactions/liked/` — liked videos
- `GET /api/v1/interactions/saved/` — saved videos
- `GET /api/v1/interactions/favourites/` — favourited videos
- `GET /api/v1/subscriptions/` — my subscriptions

---

## File Upload Security

All file uploads go through a multi-layer security pipeline:

| Step | Check |
|------|-------|
| 1 | Authentication verified |
| 2 | File size checked (max 500MB video, 10MB image) |
| 3 | Extension checked against allowlist |
| 4 | MIME type verified |
| 5 | Magic bytes / file signature verified |
| 6 | File scanned for malicious patterns |
| 7 | File renamed to random UUID (original name discarded) |
| 8 | Stored on Cloudinary (never on server filesystem) |
| 9 | Saved to DB via ORM (parameterized queries) |
| 10 | Served via signed Cloudinary URLs |

**Allowed video formats:** `.mp4`, `.mov`, `.avi`, `.mkv`, `.webm`
**Allowed image formats:** `.jpg`, `.jpeg`, `.png`, `.webp`

---


## Authentication

### Register

Creates a new user account with status `pending_verification` and sends a 6-digit OTP to the provided email. A profile row is automatically created for the user.

**Endpoint**
```
POST /auth/register/
```

**Request Body**
```json
{
  "full_name": "John Doe",
  "email": "user@example.com",
  "password": "strongpassword123"
}
```

**Validation Rules**
- `full_name` — required, user's full name
- `email` — valid email format, must be unique
- `password` — minimum 8 characters

**Success Response** `201 Created`
```json
{
  "detail": "Registration successful. Check your email for the OTP."
}
```

**Error Responses**

| Status | Detail |
|--------|--------|
| `400` | Email already exists or validation failed |

> After registration, status is `pending_verification`. Email must be verified before logging in.

---

### Login

Authenticates a user and returns JWT access and refresh tokens. Requires `active` status (email verified).

**Endpoint**
```
POST /auth/login/
```

**Request Body**
```json
{
  "email": "user@example.com",
  "password": "strongpassword123"
}
```

**Success Response** `200 OK`
```json
{
  "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "user": {
        "id": "2483bf15-de2c-4d7f-b31e-5eb9ab780bed",
        "email": "user@example.com",
        "role": "viewer",
        "full_name": "UHAa UCHEEE",
        "avatar_url": "https://lh3.googleusercontent.com/a/ACg8ocKcK44BsAJpZY1cY0sv6YaV9j8ZOEJnfJ7izuhftPFJCJQpXtsi=s96-c"
    }
}
```

**Error Responses**

| Status | Detail |
|--------|--------|
| `401` | Invalid credentials |
| `401` | Invalid credentials. N attempt(s) remaining |
| `403` | Account is not active. Please verify your email or contact support |
| `403` | Account locked. Try again in N minute(s) |

**Account Lockout Rules**
- After **5 failed login attempts**, the account is locked for **15 minutes**
- Remaining attempts are shown in the response message
- A successful login resets the failed attempt counter and clears the lock
- Lockout expires automatically after 15 minutes

---

### Logout

Invalidates the refresh token by blacklisting it.

**Endpoint**
```
POST /auth/logout/
```

**Headers**
```
Authorization: Bearer <access_token>
```

**Request Body**
```json
{
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Success Response** `200 OK`
```json
{
  "detail": "Logged out successfully."
}
```

**Error Responses**

| Status | Detail |
|--------|--------|
| `400` | Refresh token is required |
| `400` | Invalid or already blacklisted token |
| `401` | Authentication credentials were not provided |

---

## Email Verification

### Verify Email

Verifies the user's email using the 6-digit OTP sent during registration. On success, status is updated from `pending_verification` to `active`.

**Endpoint**
```
POST /auth/verify-email/
```

**Request Body**
```json
{
  "email": "user@example.com",
  "otp": "587976"
}
```

**Success Response** `200 OK`
```json
{
  "detail": "Email verified successfully."
}
```

**Error Responses**

| Status | Detail |
|--------|--------|
| `400` | Email already verified |
| `400` | OTP has expired. Request a new one |
| `400` | Invalid OTP |
| `404` | User not found |

---

### Resend OTP

Generates and resends a new 6-digit verification OTP to the user's email.

**Endpoint**
```
POST /auth/resend-otp/
```

**Request Body**
```json
{
  "email": "user@example.com"
}
```

**Success Response** `200 OK`
```json
{
  "detail": "If that email exists, a new OTP has been sent."
}
```

> Response is identical whether the email exists or not to prevent email enumeration.

**Error Responses**

| Status | Detail |
|--------|--------|
| `400` | Email already verified |

---

## Password Reset

### Forgot Password

Sends a 6-digit OTP to the user's email to initiate password reset.

**Endpoint**
```
POST /auth/forgot-password/
```

**Request Body**
```json
{
  "email": "user@example.com"
}
```

**Success Response** `200 OK`
```json
{
  "detail": "If that email exists, a reset code has been sent."
}
```

---

### Verify Reset OTP

Validates the password reset OTP. Optional but recommended for better UX.

**Endpoint**
```
POST /auth/verify-reset-otp/
```

**Request Body**
```json
{
  "email": "user@example.com",
  "otp": "839201"
}
```

**Success Response** `200 OK`
```json
{
  "detail": "OTP verified. Proceed to reset your password."
}
```

**Error Responses**

| Status | Detail |
|--------|--------|
| `400` | No reset request found |
| `400` | OTP has expired. Request a new one |
| `400` | Invalid OTP |
| `400` | Invalid request |

---

### Reset Password

Resets the user's password. OTP is re-verified at this step. Also clears any active account lockout.

**Endpoint**
```
POST /auth/reset-password/
```

**Request Body**
```json
{
  "email": "user@example.com",
  "otp": "839201",
  "new_password": "newstrongpassword123",
  "confirm_password": "newstrongpassword123"
}
```

**Validation Rules**
- `new_password` — minimum 8 characters
- `confirm_password` — must match `new_password`

**Success Response** `200 OK`
```json
{
  "detail": "Password reset successful. You can now log in."
}
```

**Error Responses**

| Status | Detail |
|--------|--------|
| `400` | Passwords do not match |
| `400` | No reset request found |
| `400` | OTP has expired. Request a new one |
| `400` | Invalid OTP |

---

## Token Management

### Refresh Access Token

Returns a new access token using a valid refresh token.

**Endpoint**
```
POST /auth/token/refresh/
```

**Request Body**
```json
{
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Success Response** `200 OK`
```json
{
  "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Error Responses**

| Status | Detail |
|--------|--------|
| `401` | Refresh token is invalid or expired |

**Token Lifetimes**

| Token | Lifetime |
|-------|----------|
| Access Token | 30 minutes |
| Refresh Token | 7 days |

---

## Profiles

### Get My Profile

Returns the authenticated user's profile.

**Endpoint**
```
GET /profile/me/
```

**Headers**
```
Authorization: Bearer <access_token>
```

**Success Response** `200 OK`
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "6b21af05-dd8f-4e06-affd-ccb2d983ceae",
  "full_name": "John Doe",
  "bio": "Content creator from Abia State",
  "avatar_url": null,
  "banner_url": null,
  "social_links": {
    "twitter": "https://twitter.com/johndoe",
    "instagram": "https://instagram.com/johndoe"
  },
  "website": "https://johndoe.com",
  "location": "Abia State, Nigeria",
  "date_of_birth": "1995-04-12",
  "is_creator_verified": false,
  "total_views": 0,
  "total_subscribers": 0,
  "created_at": "2026-06-08T07:00:00Z",
  "updated_at": "2026-06-08T07:00:00Z"
}
```

---

### Update My Profile

Updates the authenticated user's profile. All fields are optional (PATCH).

**Endpoint**
```
PATCH /profile/me/
```

**Headers**
```
Authorization: Bearer <access_token>
```

**Request Body** (all fields optional)
```json
{
  "full_name": "John Doe",
  "bio": "Content creator from Abia State",
  "avatar_url": "https://res.cloudinary.com/your-cloud/image/upload/avatar.jpg",
  "banner_url": "https://res.cloudinary.com/your-cloud/image/upload/banner.jpg",
  "website": "https://johndoe.com",
  "location": "Abia State, Nigeria",
  "date_of_birth": "1995-04-12",
  "social_links": {
    "twitter": "https://twitter.com/johndoe",
    "instagram": "https://instagram.com/johndoe"
  }
}
```

**Validation Rules**
- `social_links` — must be a JSON object if provided
- `date_of_birth` — must be a past date

**Success Response** `200 OK` — returns full updated profile object.

---

### Get Public Profile

Returns any user's public profile by their `user_id`.

**Endpoint**
```
GET /profile/<user_id>/
```

**Success Response** `200 OK` — returns full profile object.

**Error Responses**

| Status | Detail |
|--------|--------|
| `404` | No Profile matches the given query |

---

## Videos

### Upload Video (Server-side)

Upload a video file directly through Django to Cloudinary.

**Endpoint**
```
POST /videos/upload/
```

**Headers**
```
Authorization: Bearer <access_token>
Content-Type: multipart/form-data
```

**Form Fields**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `video_file` | File | ✅ | MP4, AVI, MOV, MKV, WebM (max 500MB) |
| `title` | Text | ✅ | Video title |
| `description` | Text | ❌ | Video description |
| `category` | Text | ❌ | Category ID (integer) |
| `visibility` | Text | ❌ | `public` \| `unlisted` \| `private` \| `subscribers_only` |
| `is_monetized` | Text | ❌ | `true` \| `false` |
| `revenue_share_percent` | Text | ❌ | 0–100 |
| `tag_ids` | Text | ❌ | JSON array e.g. `[1, 2]` |

> **Role required:** `creator` or `admin`

**Success Response** `201 Created`
```json
{
  "id": "4b9d0001-bd06-4184-9300-695948623d36",
  "creator_id": "6b21af05-dd8f-4e06-affd-ccb2d983ceae",
  "title": "Big Buck Bunny Test",
  "description": "Test video upload",
  "cloudinary_url": "https://res.cloudinary.com/your-cloud/video/upload/v1234/abia_stream/videos/abc123.mp4",
  "cloudinary_thumbnail_url": "https://res.cloudinary.com/your-cloud/video/upload/so_1/abia_stream/videos/abc123.jpg",
  "duration_seconds": 60,
  "width": 1280,
  "height": 720,
  "format": "mp4",
  "file_size": 5242880,
  "category": {
    "id": 1,
    "name": "Movies",
    "slug": "movies"
  },
  "tags": [
    { "id": 1, "name": "Trending", "slug": "trending", "usage_count": 1 }
  ],
  "views_count": 0,
  "likes_count": 0,
  "saves_count": 0,
  "shares_count": 0,
  "status": "processing",
  "visibility": "public",
  "is_monetized": false,
  "revenue_share_percent": null,
  "published_at": null,
  "created_at": "2026-06-14T16:41:50Z",
  "updated_at": "2026-06-14T16:41:50Z"
}
```

**Error Responses**

| Status | Detail |
|--------|--------|
| `400` | No file was submitted |
| `400` | Unsupported video format |
| `400` | File too large. Max 500MB |
| `403` | Only creators and admins can upload videos |
| `500` | Cloudinary upload failed |

---

### Get Signed Upload Params (Client-side)

Get signed credentials for direct frontend → Cloudinary upload.

**Endpoint**
```
GET /videos/upload/signed-params/
```

**Headers**
```
Authorization: Bearer <access_token>
```

**Success Response** `200 OK`
```json
{
  "timestamp": 1718380800,
  "signature": "a3f9d2...",
  "api_key": "your_api_key",
  "cloud_name": "your_cloud_name",
  "folder": "abia_stream/videos",
  "resource_type": "video",
  "upload_url": "https://api.cloudinary.com/v1_1/your_cloud_name/video/upload"
}
```

> Frontend uses these params to upload directly to Cloudinary, then calls `/videos/upload/from-cloudinary/` with the result.

---

### Save Video from Cloudinary (Client-side)

Save video metadata after frontend uploads directly to Cloudinary.

**Endpoint**
```
POST /videos/upload/from-cloudinary/
```

**Headers**
```
Authorization: Bearer <access_token>
Content-Type: application/json
```

**Request Body**
```json
{
  "cloudinary_public_id": "abia_stream/videos/abc123",
  "cloudinary_url": "https://res.cloudinary.com/your-cloud/video/upload/v1234/abia_stream/videos/abc123.mp4",
  "cloudinary_thumbnail_url": "https://res.cloudinary.com/...",
  "title": "My Video",
  "description": "Video description",
  "duration_seconds": 120,
  "width": 1920,
  "height": 1080,
  "format": "mp4",
  "file_size": 10485760,
  "bitrate": 4000,
  "category": 1,
  "visibility": "public",
  "is_monetized": false,
  "tag_ids": [1, 2]
}
```

**Success Response** `201 Created` — returns full video object.

---

### List Public Videos

Returns all published public videos. Supports optional filters.

**Endpoint**
```
GET /videos/
```

**Query Parameters**

| Param | Type | Description |
|-------|------|-------------|
| `category` | int | Filter by category ID |
| `tag` | int | Filter by tag ID |
| `creator` | uuid | Filter by creator ID |

**Examples**
```
GET /videos/
GET /videos/?category=1
GET /videos/?tag=2
GET /videos/?creator=6b21af05-dd8f-4e06-affd-ccb2d983ceae
```

**Success Response** `200 OK` — returns array of video objects.

---

### My Videos

Returns the authenticated user's own videos (all statuses).

**Endpoint**
```
GET /videos/me/
```

**Headers**
```
Authorization: Bearer <access_token>
```

**Query Parameters**

| Param | Type | Description |
|-------|------|-------------|
| `status` | string | Filter by status e.g. `draft`, `published` |

**Success Response** `200 OK` — returns array of video objects.

---

### Get Single Video

Returns a single video. Visibility rules apply.

**Endpoint**
```
GET /videos/<video_id>/
```

**Visibility Rules**
- `public` — anyone can view
- `unlisted` — anyone with the direct link
- `private` — owner only
- `subscribers_only` — subscribers only (Phase 2)

**Error Responses**

| Status | Detail |
|--------|--------|
| `403` | You do not have access to this video |
| `404` | Video not found |

---

### Update Video

Update video metadata. Owner only.

**Endpoint**
```
PATCH /videos/<video_id>/
```

**Headers**
```
Authorization: Bearer <access_token>
```

**Request Body** (all fields optional)
```json
{
  "title": "Updated Title",
  "description": "Updated description",
  "category": 2,
  "visibility": "unlisted",
  "status": "draft",
  "is_monetized": true,
  "revenue_share_percent": 70,
  "cloudinary_thumbnail_url": "https://res.cloudinary.com/...",
  "tag_ids": [1, 3]
}
```

**Validation Rules**
- `status` — can only be set to `draft`, `published`, or `archived`
- Cannot publish without a valid Cloudinary URL
- Cannot publish if status is not `ready` or `draft`
- Blocked videos cannot be edited

**Success Response** `200 OK` — returns full updated video object.

---

### Delete Video

Deletes video from both Supabase and Cloudinary. Owner only.

**Endpoint**
```
DELETE /videos/<video_id>/
```

**Headers**
```
Authorization: Bearer <access_token>
```

**Success Response** `204 No Content`
```json
{
  "detail": "Video deleted successfully."
}
```

---

### Publish Video

Publish a video that is in `ready`, `draft`, or `processing` status.

**Endpoint**
```
POST /videos/<video_id>/publish/
```

**Headers**
```
Authorization: Bearer <access_token>
```

> **Role required:** `creator` or `admin`

**Success Response** `200 OK` — returns updated video object with `status: published`.

**Error Responses**

| Status | Detail |
|--------|--------|
| `400` | Cannot publish a video with status: {current_status} |
| `403` | Only creators and admins can upload videos |
| `404` | Not found |

---

### Archive Video

Archive a published video.

**Endpoint**
```
POST /videos/<video_id>/archive/
```

**Headers**
```
Authorization: Bearer <access_token>
```

> **Role required:** `creator` or `admin`

**Success Response** `200 OK` — returns updated video object with `status: archived`.

**Error Responses**

| Status | Detail |
|--------|--------|
| `400` | Only published videos can be archived |

---

## Categories

### List Categories

Returns all active categories ordered by display order.

**Endpoint**
```
GET /categories/
```

**Success Response** `200 OK`
```json
[
  {
    "id": 1,
    "name": "Movies",
    "slug": "movies",
    "description": "Feature films and cinema",
    "thumbnail_url": null,
    "display_order": 1
  }
]
```

---

## Tags

### List Tags

Returns all tags ordered by usage count.

**Endpoint**
```
GET /tags/
```

**Success Response** `200 OK`
```json
[
  {
    "id": 1,
    "name": "Trending",
    "slug": "trending",
    "usage_count": 5
  }
]
```

---

## Enums Reference

### `user_role`

| Value | Description |
|-------|-------------|
| `viewer` | Default role for new users |
| `creator` | Can upload and manage videos |
| `moderator` | Content management access |
| `admin` | Full access |

### `user_status`

| Value | Description |
|-------|-------------|
| `pending_verification` | Newly registered, email not yet verified |
| `active` | Email verified, can log in |
| `suspended` | Temporarily restricted |
| `banned` | Permanently restricted |

### `video_status`

| Value | Description |
|-------|-------------|
| `draft` | Saved but not submitted |
| `processing` | Cloudinary is transcoding |
| `ready` | Cloudinary finished, ready to publish |
| `published` | Live and visible to public |
| `archived` | Hidden from public, kept by creator |
| `failed` | Cloudinary processing failed |
| `blocked` | Blocked by admin |

### `video_visibility`

| Value | Description |
|-------|-------------|
| `public` | Visible to everyone |
| `unlisted` | Accessible via direct link only |
| `private` | Visible to owner only |
| `subscribers_only` | Visible to subscribers (Phase 2) |

### `interaction_type`

| Value | Description |
|-------|-------------|
| `like` | User liked the video |
| `dislike` | User disliked the video |
| `save` | User saved the video |
| `favorite` | User favorited the video |
| `report` | User reported the video |

### `livestream_status`

| Value | Description |
|-------|-------------|
| `scheduled` | Scheduled for future |
| `live` | Currently streaming |
| `ended` | Stream ended |
| `cancelled` | Stream cancelled |
| `faild` | Stream failed ⚠️ typo in DB |

---

## Error Responses

All error responses:
```json
{
  "detail": "Human-readable error message."
}
```

Validation errors:
```json
{
  "field_name": ["Error message."]
}
```

---

## Status Codes

| Code | Meaning |
|------|---------|
| `200` | OK |
| `201` | Created |
| `204` | No Content |
| `400` | Bad Request |
| `401` | Unauthorized |
| `403` | Forbidden |
| `404` | Not Found |
| `500` | Internal Server Error |

---

## Full Flow Summary

```
Auth:
1. POST /auth/register/              → OTP sent, profile auto-created
2. POST /auth/verify-email/          → status → active
3. POST /auth/login/                 → access + refresh tokens
4. POST /auth/token/refresh/         → new access token
5. POST /auth/logout/                → blacklist refresh token

Password Reset:
1. POST /auth/forgot-password/       → OTP sent
2. POST /auth/verify-reset-otp/      → confirm OTP
3. POST /auth/reset-password/        → new password set

Video Upload (Server-side):
1. POST /videos/upload/              → file → Django → Cloudinary → DB

Video Upload (Client-side):
1. GET  /videos/upload/signed-params/ → get credentials
2. Frontend uploads directly to Cloudinary
3. POST /videos/upload/from-cloudinary/ → save metadata to DB

Video Publishing:
1. POST /videos/<id>/publish/        → status → published
2. POST /videos/<id>/archive/        → status → archived

Interactions:
POST /interactions/                  → like/unlike, save/unsave, favourite, dislike, report
GET  /interactions/video/<id>/status/ → check my interactions on a video
GET  /interactions/liked/            → my liked videos
GET  /interactions/saved/            → my saved videos

Subscriptions:
POST /subscriptions/<slug>/          → subscribe/unsubscribe toggle
GET  /subscriptions/                 → my subscriptions
GET  /subscriptions/<slug>/status/   → check subscription status

Creator Dashboard:
GET  /channels/me/dashboard/         → stats summary
GET  /channels/me/performance/       → views chart (7d/28d/90d)
GET  /channels/me/content/           → my videos with stats
GET  /channels/me/videos/<id>/analytics/ → single video analytics
```

---

## Upload Role Restrictions

| Role | Can Upload | Can Publish | Can Archive |
|------|-----------|-------------|-------------|
| `viewer` | ❌ | ❌ | ❌ |
| `creator` | ✅ | ✅ own videos | ✅ own videos |
| `moderator` | ❌ | ❌ | ❌ |
| `admin` | ✅ | ✅ | ✅ |

---

## Postman Quick Setup

1. Environment: `Abia-Stream-Dev`
2. Variable: `base_url` = `http://127.0.0.1:8000/api/v1`
3. Login **Scripts → Post-response**:

```javascript
if (pm.response.code === 200) {
    const res = pm.response.json();
    pm.environment.set("access_token", res.access);
    pm.environment.set("refresh_token", res.refresh);
}
```

4. Protected requests → Authorization → Bearer Token → `{{access_token}}`
5. Video upload → Body → **form-data** (not raw JSON)
6. `video_file` key type must be set to **File** not Text

---

*Last updated: June 2026*

---

## Playback

### Record a View

Records a video view. Works for both authenticated and anonymous users.
Called when a user starts watching a video.

**Endpoint**
```
POST /playback/view/
```

**Request Body**
```json
{
  "video_id": "4b9d0001-bd06-4184-9300-695948623d36",
  "watch_duration_seconds": 0,
  "completed": false,
  "device_type": "desktop",
  "referrer": "https://google.com",
  "session_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Field Reference**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `video_id` | uuid | ✅ | Video being watched |
| `watch_duration_seconds` | int | ❌ | Seconds watched so far |
| `completed` | bool | ❌ | Whether video was completed |
| `device_type` | string | ❌ | `desktop` \| `mobile` \| `tablet` |
| `referrer` | string | ❌ | Where the user came from |
| `session_id` | uuid | ❌ | Browser session ID |

**Success Response** `200 OK`
```json
{
  "detail": "View recorded."
}
```

> Records a row in `view_logs` and increments `views_count` on the video. Anonymous users are tracked by `session_id` and `ip_address`.

---

### Update Watch Progress

Update the user's watch progress for a video. Called every 15–30 seconds while watching.

**Endpoint**
```
POST /playback/progress/
```

**Headers**
```
Authorization: Bearer <access_token>
```

**Request Body**
```json
{
  "video_id": "4b9d0001-bd06-4184-9300-695948623d36",
  "watch_progress_seconds": 150,
  "completed": false,
  "device_type": "desktop",
  "session_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Success Response** `200 OK`
```json
{
  "id": "uuid",
  "video_id": "4b9d0001-bd06-4184-9300-695948623d36",
  "video_title": "Big Buck Bunny Test",
  "video_thumbnail": "https://res.cloudinary.com/...",
  "video_duration": 360,
  "watch_progress_seconds": 150,
  "completed": false,
  "device_type": "desktop",
  "last_watched_at": "2026-06-14T17:00:00Z"
}
```

> Auto-marks `completed = true` when progress reaches 90% of video duration. Uses `update_or_create` — creates a new entry on first watch, updates on rewatch.

---

### Get Watch History

Returns the authenticated user's full watch history ordered by most recently watched.

**Endpoint**
```
GET /playback/history/
```

**Headers**
```
Authorization: Bearer <access_token>
```

**Success Response** `200 OK`
```json
[
  {
    "id": "uuid",
    "video_id": "4b9d0001-bd06-4184-9300-695948623d36",
    "video_title": "Big Buck Bunny Test",
    "video_thumbnail": "https://res.cloudinary.com/...",
    "video_duration": 360,
    "watch_progress_seconds": 324,
    "completed": true,
    "device_type": "desktop",
    "last_watched_at": "2026-06-14T17:00:00Z"
  }
]
```

---

### Clear Watch History

Clears the authenticated user's entire watch history.

**Endpoint**
```
DELETE /playback/history/clear/
```

**Headers**
```
Authorization: Bearer <access_token>
```

**Success Response** `200 OK`
```json
{
  "detail": "Watch history cleared. 5 entries removed."
}
```

---

### Remove Single Video from History

Removes a single video from the user's watch history.

**Endpoint**
```
DELETE /playback/history/<video_id>/
```

**Headers**
```
Authorization: Bearer <access_token>
```

**Success Response** `200 OK`
```json
{
  "detail": "Removed from watch history."
}
```

**Error Responses**

| Status | Detail |
|--------|--------|
| `404` | Not found |

---

### Continue Watching

Returns videos the user has started but not yet completed, ordered by most recently watched. Used for the "Continue Watching" row on the home page.

**Endpoint**
```
GET /playback/continue-watching/
```

**Headers**
```
Authorization: Bearer <access_token>
```

**Success Response** `200 OK`
```json
[
  {
    "id": "uuid",
    "video_id": "4b9d0001-bd06-4184-9300-695948623d36",
    "video_title": "Big Buck Bunny Test",
    "video_thumbnail": "https://res.cloudinary.com/...",
    "video_duration": 360,
    "watch_progress_seconds": 150,
    "completed": false,
    "device_type": "mobile",
    "last_watched_at": "2026-06-14T17:00:00Z"
  }
]
```

> Only returns videos where `completed = false` and `watch_progress_seconds > 0`. Max 20 results.

---

## Playback Endpoints Summary

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/api/v1/playback/view/` | Record a view | Public |
| `POST` | `/api/v1/playback/progress/` | Update watch progress | 🔒 |
| `GET` | `/api/v1/playback/history/` | Get watch history | 🔒 |
| `DELETE` | `/api/v1/playback/history/clear/` | Clear all history | 🔒 |
| `DELETE` | `/api/v1/playback/history/<video_id>/` | Remove one video | 🔒 |
| `GET` | `/api/v1/playback/continue-watching/` | Unfinished videos | 🔒 |

---

## Playback Flow

```
User clicks play:
  POST /playback/view/                  → log view, increment views_count

Every 15-30 seconds while watching:
  POST /playback/progress/              → update progress in watch_history

User finishes or closes player:
  POST /playback/progress/ (final)      → mark completed if >= 90%

User opens home page:
  GET  /playback/continue-watching/     → show "Continue Watching" row

User opens history page:
  GET  /playback/history/               → show full watch history
```

---

## How `view_logs` and `watch_history` differ

| | `watch_history` | `view_logs` |
|---|---|---|
| Rows | One per user per video | One per view event |
| Updated | Yes, on every progress update | No, insert only |
| Tracks | Progress + completion | IP, device, duration |
| Purpose | Continue watching, history | Analytics |
| Anonymous | ❌ Requires login | ✅ Works anonymously |

---

## Creator Channels

### List All Channels

Returns all creator channels ordered by most recently created.

**Endpoint**
```
GET /channels/
```

**Success Response** `200 OK`
```json
[
  {
    "id": "uuid",
    "owner_id": "uuid",
    "owner_role": "creator",
    "channel_name": "Abia Vibes",
    "channel_slug": "abia-vibes",
    "banner_url": null,
    "channel_description": "Best content from Abia State",
    "subscriber_count": 0,
    "total_videos": 0,
    "is_verified": false,
    "custom_thumbnail_url": null,
    "created_at": "2026-06-27T00:00:00Z",
    "updated_at": "2026-06-27T00:00:00Z"
  }
]
```

---

### Create Channel

Creates a creator channel for the authenticated user. Automatically promotes user role from `viewer` to `creator`.

**Endpoint**
```
POST /channels/create/
```

**Headers**
```
Authorization: Bearer <access_token>
```

**Request Body**
```json
{
  "channel_name": "Abia Vibes",
  "channel_description": "Best content from Abia State",
  "banner_url": "https://res.cloudinary.com/your-cloud/image/upload/banner.jpg",
  "custom_thumbnail_url": "https://res.cloudinary.com/your-cloud/image/upload/thumb.jpg"
}
```

**Validation Rules**
- `channel_name` — required, letters/numbers/spaces/hyphens/underscores only
- `channel_name` — must be unique (slug is auto-generated)
- Only one channel per user allowed

**Success Response** `201 Created`
```json
{
  "id": "uuid",
  "owner_id": "uuid",
  "owner_email": "creator@example.com",
  "owner_role": "creator",
  "channel_name": "Abia Vibes",
  "channel_slug": "abia-vibes",
  "banner_url": null,
  "channel_description": "Best content from Abia State",
  "subscriber_count": 0,
  "total_videos": 0,
  "is_verified": false,
  "custom_thumbnail_url": null,
  "created_at": "2026-06-27T00:00:00Z",
  "updated_at": "2026-06-27T00:00:00Z"
}
```

**Error Responses**

| Status | Detail |
|--------|--------|
| `400` | You already have a channel |
| `400` | A channel with this name already exists |
| `400` | Channel name can only contain letters, numbers, spaces, hyphens and underscores |
| `401` | Authentication credentials were not provided |

> After creating a channel, the user's role is automatically promoted from `viewer` to `creator`, enabling video upload permissions.

---

### Get My Channel

Returns the authenticated user's own channel.

**Endpoint**
```
GET /channels/me/
```

**Headers**
```
Authorization: Bearer <access_token>
```

**Success Response** `200 OK` — returns full channel object.

**Error Responses**

| Status | Detail |
|--------|--------|
| `404` | No channel found |

---

### Update My Channel

Updates the authenticated user's channel. All fields optional (PATCH).

**Endpoint**
```
PATCH /channels/me/
```

**Headers**
```
Authorization: Bearer <access_token>
```

**Request Body** (all fields optional)
```json
{
  "channel_name": "Abia Vibes Updated",
  "channel_description": "Updated description",
  "banner_url": "https://res.cloudinary.com/...",
  "custom_thumbnail_url": "https://res.cloudinary.com/..."
}
```

> Updating `channel_name` automatically updates `channel_slug`.

**Success Response** `200 OK` — returns updated channel object.

---

### Delete My Channel

Deletes the authenticated user's channel and demotes role back to `viewer`.

**Endpoint**
```
DELETE /channels/me/delete/
```

**Headers**
```
Authorization: Bearer <access_token>
```

**Success Response** `200 OK`
```json
{
  "detail": "Channel deleted successfully."
}
```

> After deletion, the user's role is demoted from `creator` back to `viewer`, removing video upload permissions.

---

### Get Public Channel

Returns any creator channel by its slug.

**Endpoint**
```
GET /channels/<channel_slug>/
```

**Example**
```
GET /channels/abia-vibes/
```

**Success Response** `200 OK` — returns full channel object.

**Error Responses**

| Status | Detail |
|--------|--------|
| `404` | No channel found |

---

### Get Channel Videos

Returns all published public videos for a channel.

**Endpoint**
```
GET /channels/<channel_slug>/videos/
```

**Example**
```
GET /channels/abia-vibes/videos/
```

**Success Response** `200 OK` — returns array of video objects ordered by `published_at` descending.

---

## Creator Channels Endpoints Summary

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `GET` | `/api/v1/channels/` | List all channels | Public |
| `POST` | `/api/v1/channels/create/` | Create channel | 🔒 |
| `GET` | `/api/v1/channels/me/` | Get my channel | 🔒 |
| `PATCH` | `/api/v1/channels/me/` | Update my channel | 🔒 |
| `DELETE` | `/api/v1/channels/me/delete/` | Delete my channel | 🔒 |
| `GET` | `/api/v1/channels/<slug>/` | Get public channel | Public |
| `GET` | `/api/v1/channels/<slug>/videos/` | Get channel videos | Public |

---

## Channel & Role Flow

```
Any logged-in user:
POST /channels/create/       → channel created, role: viewer → creator
                               user can now upload videos

Creator updates channel:
PATCH /channels/me/          → channel updated, slug auto-updated if name changed

Creator deletes channel:
DELETE /channels/me/delete/  → channel deleted, role: creator → viewer
                               upload permissions removed
```

---

## Enum Corrections

Based on actual Supabase database values:

| Enum | Correct Value | Previous (wrong) |
|------|--------------|-----------------|
| `interaction_type` | `favourite` | `favorite` |
| `livestream_status` | `failed` | `faild` |

---

## Subscriptions

### Subscribe / Unsubscribe

Toggle subscription to a channel. First call subscribes, second call unsubscribes.

**Endpoint**
```
POST /api/v1/subscriptions/<channel_slug>/
```

**Headers**
```
Authorization: Bearer <access_token>
```

**Subscribe Response** `201 Created`
```json
{
    "detail": "Subscribed to Abia Vibes.",
    "action": "subscribed",
    "channel_slug": "abia-vibes",
    "subscriber_count": 101
}
```

**Unsubscribe Response** `200 OK`
```json
{
    "detail": "Unsubscribed from Abia Vibes.",
    "action": "unsubscribed",
    "channel_slug": "abia-vibes",
    "subscriber_count": 100
}
```

**Error Responses**

| Status | Detail |
|--------|--------|
| `400` | You cannot subscribe to your own channel |
| `404` | Channel not found |

> Subscribing automatically increments `subscriber_count` on `creator_channels` and `total_subscribers` on `profiles`. Also sends a notification to the channel owner.

---

### My Subscriptions

Returns all channels the authenticated user subscribes to.

**Endpoint**
```
GET /api/v1/subscriptions/
```

**Headers**
```
Authorization: Bearer <access_token>
```

**Success Response** `200 OK` — paginated list of subscriptions.

```json
{
    "pagination": {
        "total": 5,
        "page": 1,
        "page_size": 8,
        "total_pages": 1,
        "next": null,
        "previous": null
    },
    "results": [
        {
            "id": "uuid",
            "channel_id": "uuid",
            "channel_name": "Abia Vibes",
            "channel_slug": "abia-vibes",
            "channel_thumbnail": null,
            "subscriber_count": 101,
            "created_at": "2026-06-27T00:00:00Z"
        }
    ]
}
```

---

### Subscription Status

Check if the authenticated user is subscribed to a channel.

**Endpoint**
```
GET /api/v1/subscriptions/<channel_slug>/status/
```

**Headers**
```
Authorization: Bearer <access_token>
```

**Success Response** `200 OK`
```json
{
    "channel_slug": "abia-vibes",
    "channel_name": "Abia Vibes",
    "is_subscribed": true,
    "subscriber_count": 101
}
```

---

### Channel Subscribers

Returns subscriber count and list for a channel.

**Endpoint**
```
GET /api/v1/subscriptions/<channel_slug>/subscribers/
```

**Success Response** `200 OK`
```json
{
    "channel_name": "Abia Vibes",
    "subscriber_count": 101,
    "subscribers": [
        {
            "id": "uuid",
            "subscribed_at": "2026-06-27T00:00:00Z"
        }
    ]
}
```

---

## Subscriptions Endpoints Summary

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/api/v1/subscriptions/<slug>/` | Subscribe/Unsubscribe toggle | 🔒 |
| `GET` | `/api/v1/subscriptions/` | My subscriptions | 🔒 |
| `GET` | `/api/v1/subscriptions/<slug>/status/` | Subscription status | 🔒 |
| `GET` | `/api/v1/subscriptions/<slug>/subscribers/` | Channel subscribers | Public |

---

## Interactions

### Interact with a Video

Like, dislike, save, favourite, or report a video. Each interaction toggles — calling the same endpoint twice removes the interaction.

**Endpoint**
```
POST /api/v1/interactions/
```

**Headers**
```
Authorization: Bearer <access_token>
```

**Request Body**
```json
{
    "video_id": "4b9d0001-bd06-4184-9300-695948623d36",
    "interaction_type": "like"
}
```

**Interaction Types**

| Value | Description | Updates Counter |
|-------|-------------|-----------------|
| `like` | Like a video | `likes_count + 1` |
| `dislike` | Dislike a video | — |
| `save` | Save a video | `saves_count + 1` |
| `favourite` | Favourite a video | — |
| `report` | Report a video | — |

**Add Response** `201 Created`
```json
{
    "detail": "Like added.",
    "action": "added",
    "interaction_type": "like",
    "id": "uuid"
}
```

**Remove Response** `200 OK`
```json
{
    "detail": "Like removed.",
    "action": "removed",
    "interaction_type": "like"
}
```

**Error Responses**

| Status | Detail |
|--------|--------|
| `400` | You cannot report your own video |
| `404` | Video not found |

> **Like and Dislike are mutually exclusive** — liking a video automatically removes a dislike and vice versa.

---

### Video Interaction Status

Check which interactions the current user has on a video.

**Endpoint**
```
GET /api/v1/interactions/video/<video_id>/status/
```

**Headers**
```
Authorization: Bearer <access_token>
```

**Success Response** `200 OK`
```json
{
    "video_id": "uuid",
    "liked": true,
    "disliked": false,
    "saved": false,
    "favourited": false,
    "reported": false,
    "likes_count": 42,
    "saves_count": 15
}
```

---

### Video Interaction Counts

Returns public interaction counts for a video.

**Endpoint**
```
GET /api/v1/interactions/video/<video_id>/counts/
```

**Success Response** `200 OK`
```json
{
    "video_id": "uuid",
    "likes_count": 42,
    "saves_count": 15,
    "views_count": 1200,
    "shares_count": 8
}
```

---

### My Liked Videos

**Endpoint**
```
GET /api/v1/interactions/liked/
```

**Headers**
```
Authorization: Bearer <access_token>
```

**Success Response** `200 OK` — paginated list of liked video interactions.

---

### My Saved Videos

**Endpoint**
```
GET /api/v1/interactions/saved/
```

**Success Response** `200 OK` — paginated list of saved video interactions.

---

### My Favourited Videos

**Endpoint**
```
GET /api/v1/interactions/favourites/
```

**Success Response** `200 OK` — paginated list of favourited video interactions.

---

## Interactions Endpoints Summary

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/api/v1/interactions/` | Add/Remove interaction | 🔒 |
| `GET` | `/api/v1/interactions/video/<id>/status/` | My interaction status | 🔒 |
| `GET` | `/api/v1/interactions/video/<id>/counts/` | Video counts | Public |
| `GET` | `/api/v1/interactions/liked/` | My liked videos | 🔒 |
| `GET` | `/api/v1/interactions/saved/` | My saved videos | 🔒 |
| `GET` | `/api/v1/interactions/favourites/` | My favourited videos | 🔒 |


---

## Notifications

### List Notifications

Returns the authenticated user's notifications ordered by most recent.

**Endpoint**
```
GET /api/v1/notifications/
```

**Headers**
```
Authorization: Bearer <access_token>
```

**Query Parameters**

| Param | Type | Description |
|-------|------|-------------|
| `is_read` | bool | Filter by read status (`true` or `false`) |
| `type` | string | Filter by notification type |

**Success Response** `200 OK` — paginated
```json
{
    "pagination": {
        "total": 5,
        "page": 1,
        "page_size": 8,
        "total_pages": 1,
        "next": null,
        "previous": null
    },
    "results": [
        {
            "id": "uuid",
            "notification_type": "new_subscriber",
            "title": "New Subscriber",
            "message": "john@example.com subscribed to your channel",
            "data": {
                "subscriber_id": "uuid",
                "channel_id": "uuid"
            },
            "is_read": false,
            "is_archived": false,
            "created_at": "2026-07-03T03:48:33Z"
        }
    ]
}
```

---

### Mark Notification as Read

Marks a single notification as read.

**Endpoint**
```
PATCH /api/v1/notifications/<notification_id>/read/
```

**Headers**
```
Authorization: Bearer <access_token>
```

**Success Response** `200 OK`
```json
{
    "detail": "Notification marked as read."
}
```

**Error Responses**

| Status | Detail |
|--------|--------|
| `404` | Notification not found |

---

### Mark All as Read

Marks all unread notifications as read.

**Endpoint**
```
PATCH /api/v1/notifications/read-all/
```

**Headers**
```
Authorization: Bearer <access_token>
```

**Success Response** `200 OK`
```json
{
    "detail": "5 notifications marked as read."
}
```

---

### Archive Notification

Archives a single notification.

**Endpoint**
```
PATCH /api/v1/notifications/<notification_id>/archive/
```

**Headers**
```
Authorization: Bearer <access_token>
```

**Success Response** `200 OK`
```json
{
    "detail": "Notification archived."
}
```

---

### Delete Notification

Permanently deletes a notification.

**Endpoint**
```
DELETE /api/v1/notifications/<notification_id>/
```

**Headers**
```
Authorization: Bearer <access_token>
```

**Success Response** `200 OK`
```json
{
    "detail": "Notification deleted."
}
```

---

### Unread Count

Returns the count of unread notifications. Used for the notification badge on the frontend.

**Endpoint**
```
GET /api/v1/notifications/unread-count/
```

**Headers**
```
Authorization: Bearer <access_token>
```

**Success Response** `200 OK`
```json
{
    "unread_count": 3
}
```

---

## Notification Types

| Type | Triggered by |
|------|-------------|
| `new_subscriber` | Someone subscribes to your channel |
| `new_like` | Someone likes your video |
| `new_comment` | Someone comments on your video (Phase 3) |
| `video_published` | Your video finishes processing and is ready |
| `new_video` | A channel you subscribe to uploads a new video |

---

## Notifications Endpoints Summary

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `GET` | `/api/v1/notifications/` | List notifications | 🔒 |
| `GET` | `/api/v1/notifications/unread-count/` | Unread count | 🔒 |
| `PATCH` | `/api/v1/notifications/<id>/read/` | Mark as read | 🔒 |
| `PATCH` | `/api/v1/notifications/read-all/` | Mark all as read | 🔒 |
| `PATCH` | `/api/v1/notifications/<id>/archive/` | Archive notification | 🔒 |
| `DELETE` | `/api/v1/notifications/<id>/` | Delete notification | 🔒 |

---

## Video Delivery & Streaming

Every video object now carries a `streaming_url` next to `cloudinary_url`:

| Field | What it is |
|-------|-----------|
| `cloudinary_url` | Progressive MP4 (unchanged for public videos) |
| `streaming_url` | Adaptive-bitrate HLS playlist (`.m3u8`). Prefer this in the player (hls.js / native Safari). `null` for drafts with no upload yet |
| `cloudinary_thumbnail_url` | Thumbnail |

### Private, unlisted and subscribers-only videos

Public videos are stored and served exactly as before. Every other visibility is stored as a Cloudinary **authenticated** asset: the plain URL no longer works, and the API returns **signed** URLs (`.../video/authenticated/s--<sig>--/...`) only to someone allowed to watch (the owner, subscribers for `subscribers_only`, anyone with the link for `unlisted`). If the server has a Cloudinary token key configured, signed URLs also expire (default 1 hour) — re-fetch the video to get a fresh one.

Changing a video's visibility moves the asset in the background; there is nothing for the frontend to do.

### Uploading a non-public video directly to Cloudinary

```
GET /videos/upload/signed-params/?visibility=private
```

When `visibility` is anything other than `public`, the response includes `"type": "authenticated"`, and the signature covers it — **send `type` along with the other fields in the Cloudinary upload form**, or Cloudinary rejects the signature. Without the query parameter the response is identical to before.

If the frontend does not send `type` (older clients), the upload still works; the backend moves the asset to authenticated storage shortly after `from-cloudinary` is called.

---

## Discovery

### Search
```
GET /videos/search/?q=<text>
```
Full-text search over title (weighted higher) and description of published public videos. Relevance first, view count breaks ties. Paginated. `400` if `q` is missing.

### Trending
```
GET /videos/trending/?days=7
```
Up to 50 videos ranked by completion-weighted views in the last `days` (1–90). Not paginated.

### For You feed
```
GET /videos/feed/?page=1&page_size=8
```
Personalized home feed; works signed out too. Paginated; each video has an extra `feed_reason`:

| `feed_reason` | Meaning |
|---------------|---------|
| `related` | Watched together with something you watched recently |
| `subscription` | New from a channel you subscribe to |
| `category` | Popular in a category you watch a lot |
| `trending` | Trending platform-wide |
| `fresh` | Recently uploaded |

Your own videos and videos you finished are left out, and one creator cannot fill a whole page.

### Related videos
```
GET /videos/<video_id>/related/
```
"People who watched this also watched". Recomputed nightly. Returns `[]` until enough watch history exists.

### Behaviour events
```
POST /events/
```
```json
{
  "events": [
    {"event_type": "impression", "session_id": "<uuid>", "video_id": "<uuid>"},
    {"event_type": "play", "session_id": "<uuid>", "video_id": "<uuid>", "payload": {"position": 0}}
  ]
}
```
Batch of up to 100. `event_type`: `search`, `search_result_click`, `impression`, `video_click`, `play`, `pause`, `seek`, `skip`, `complete`. Auth optional. Send the same `X-Session-Id` / `session_id` for a browsing session. `201 {"recorded": 2}`. Rate limited to 120 requests/min.

### Experiments
```
GET /experiments/variants/
```
`{"feed_v2": "treatment"}` — the caller's sticky variant for each active A/B test. Send `X-Session-Id` when signed out.

---

## Reporting Content

### Report a video or comment
```
POST /reports/
```
🔒
```json
{"video_id": "<uuid>", "reason": "spam", "details": "optional"}
```
or `{"comment_id": "<uuid>", ...}` — exactly one of the two.

`reason`: `spam`, `harassment`, `hate`, `violence`, `sexual`, `child_safety`, `copyright`, `misinformation`, `other`.

`201 Created` for a new report; `200 OK` with the existing report if you already have an open report on it. `400` for your own content. Limited to 30 reports/hour.

> The existing one-click `report` interaction (`POST /interactions/`) still works and also feeds the moderation queue, with reason `other`.

### My reports
```
GET /reports/
```
🔒 Paginated list of your reports and their status (`open`, `actioned`, `dismissed`).

---

## Moderation

Requires role `moderator` or `admin`. Everyone else gets `403`.

### Queue
```
GET /moderation/queue/?target_type=video|comment&status=open
```
One row per reported item, most-reported first:
```json
{
  "target_type": "video",
  "target": {"id": "...", "title": "...", "status": "published", "creator_email": "..."},
  "report_count": 3,
  "reasons": {"spam": 2, "hate": 1},
  "first_reported_at": "...",
  "last_reported_at": "..."
}
```

### Reports for one item
```
GET /moderation/reports/?video_id=<uuid>   (or ?comment_id=<uuid>, &status=)
```

### Take action
```
POST /moderation/actions/
```
```json
{"action": "block_video", "video_id": "<uuid>", "note": "Spam links"}
```

| `action` | Target | Effect |
|----------|--------|--------|
| `block_video` | `video_id` | Status → `blocked` (hidden everywhere, creator can't edit or republish). Resolves open reports. Notifies creator |
| `restore_video` | `video_id` | Back to the status it had before the block |
| `remove_comment` | `comment_id` | Hidden (text kept for appeal). Resolves open reports. Notifies author |
| `restore_comment` | `comment_id` | Un-hides a comment removed by moderation |
| `suspend_user` | `user_id` | Status → `suspended`; their tokens stop working. Moderators can't suspend staff; nobody can suspend an admin |
| `unsuspend_user` | `user_id` | Status → `active` |
| `dismiss` | `video_id` or `comment_id` | Closes open reports with no change |

`201` with the audit record and `reports_resolved`; `400` with a reason if the action doesn't apply (e.g. already blocked).

### Audit log
```
GET /moderation/actions/?video_id=&comment_id=&user_id=
```

---

## Platform Analytics

Requires role `admin`. `period` is `1d`, `7d`, `28d` or `90d`.

| Endpoint | Returns |
|----------|---------|
| `GET /analytics/overview/?period=28d` | Users (total, new, by role/status), videos (total, uploads, by status), engagement (views, completion rate, watch hours, sessions, % change vs previous period, new subscriptions), moderation backlog |
| `GET /analytics/daily/?period=28d` | One row per day: views, watch hours, new users, uploads |
| `GET /analytics/top-videos/?period=7d&limit=20` | Most-viewed videos with completion rate |
| `GET /analytics/search/?period=7d&limit=20` | Top search queries and **zero-result** queries (content people want but can't find) |

---

## New Notification Types

| Type | Triggered by |
|------|-------------|
| `video_blocked` | A moderator removed your video |
| `video_restored` | A moderator restored your video |
| `comment_removed` | A moderator removed your comment |

---

## Discovery, Moderation & Analytics Endpoints Summary

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `GET` | `/api/v1/videos/search/?q=` | Full-text search | — |
| `GET` | `/api/v1/videos/trending/` | Trending videos | — |
| `GET` | `/api/v1/videos/feed/` | For You feed | optional |
| `GET` | `/api/v1/videos/<id>/related/` | Related videos | — |
| `POST` | `/api/v1/events/` | Record behaviour events | optional |
| `GET` | `/api/v1/experiments/variants/` | A/B variants | optional |
| `POST` | `/api/v1/reports/` | Report a video/comment | 🔒 |
| `GET` | `/api/v1/reports/` | My reports | 🔒 |
| `GET` | `/api/v1/moderation/queue/` | Moderation queue | 🛡 moderator |
| `GET` | `/api/v1/moderation/reports/` | Reports for an item | 🛡 moderator |
| `POST` | `/api/v1/moderation/actions/` | Take a moderation action | 🛡 moderator |
| `GET` | `/api/v1/moderation/actions/` | Audit log | 🛡 moderator |
| `GET` | `/api/v1/analytics/overview/` | Platform overview | 🛡 admin |
| `GET` | `/api/v1/analytics/daily/` | Daily series | 🛡 admin |
| `GET` | `/api/v1/analytics/top-videos/` | Top videos | 🛡 admin |
| `GET` | `/api/v1/analytics/search/` | Search insights | 🛡 admin |


---

## Livestreaming

Creators broadcast from OBS (or any RTMP encoder / mobile app); viewers watch over HLS. Powered by Cloudinary Live Streaming.

**Who can go live:** verified creators (identity verification approved) who have a channel. Up to 5 scheduled/live streams at a time.

### Lifecycle

```
scheduled ──(encoder connects)──▶ live ──(encoder stops / "end")──▶ ended
    └──(cancel)──▶ cancelled                      (recording → video)
```

There is no "start" button: the stream goes **live automatically** when the creator's encoder connects. If the encoder drops, the stream stays live for 2 minutes so it can reconnect; after that it ends. Maximum length 4 hours.

### Create a stream
```
POST /livestreams/
```
🔒 verified creator
```json
{
  "title": "Friday night Q&A",
  "description": "optional",
  "scheduled_start_time": "2026-10-09T19:00:00Z",
  "thumbnail_url": "https://res.cloudinary.com/...",
  "chat_enabled": true,
  "save_recording": true,
  "publish_recording": false
}
```
`201` returns the **owner view**, which includes the encoder settings:
```json
{
  "id": "…", "status": "scheduled",
  "rtmp_url": "rtmp://live.cloudinary.com/streams",
  "stream_key": "…",
  "hls_url": "https://…_hls.m3u8",
  "save_recording": true, "publish_recording": false,
  "...": "public fields below"
}
```
> **OBS setup:** Settings → Stream → Service: *Custom*, Server: `rtmp_url`, Stream Key: `stream_key`. Treat the key like a password — anyone with it can broadcast on this stream. It is only ever returned to the owner.

`403` with a reason if the user isn't verified or has no channel.

`save_recording` is fixed at creation. `publish_recording: true` publishes the recording to the channel automatically; otherwise it lands as a ready-to-publish video in *My Videos*.

### Watch / poll a stream
```
GET /livestreams/<id>/
```
Public. Poll every ~10 s on the watch page (or use the websocket below) to see it go live.

| Field | Notes |
|-------|-------|
| `status` | `scheduled`, `live`, `ended` (`cancelled`/`failed` are hidden from the public) |
| `playback_url` | HLS `.m3u8` — **only set while `live`**. Play with hls.js / native Safari |
| `viewer_count`, `max_concurrent_viewers` | |
| `creator` | `{id, channel_name, channel_slug, is_verified}` |
| `recording_video_id` | Set once the recording is published — link to the normal video page |

### Lists
```
GET /livestreams/                  live now (most viewers first), then upcoming
GET /livestreams/?status=live|scheduled|ended
GET /livestreams/me/               🔒 the creator's own streams, owner view
```

### Creator controls (owner only)
```
PATCH /livestreams/<id>/           title, description, scheduled_start_time, thumbnail_url,
                                   chat_enabled, publish_recording (only publish_recording after it ends)
POST  /livestreams/<id>/end/       stop now (stopping the encoder also ends it)
POST  /livestreams/<id>/cancel/    before it goes live
```

### Viewer count
```
POST /livestreams/<id>/heartbeat/
{"session_id": "<uuid, stable per tab>"}
```
Call every ~20 s while the player is open. Returns `{"status": "live", "viewer_count": 12}`. A viewer stops counting a minute after their last heartbeat.

### Live chat
```
GET  /livestreams/<id>/chat/                    latest 100, oldest first
GET  /livestreams/<id>/chat/?after=<message_id> newer than a message (polling)
POST /livestreams/<id>/chat/   {"content": "…"} 🔒 1–500 chars, 20/min
DELETE /livestreams/chat/<message_id>/          🔒 author, stream owner, or moderator
```
Message: `{"id", "livestream_id", "user": {"id", "display_name", "avatar_url"}, "content", "created_at"}`. Chat is open while the stream is scheduled or live, and read-only after.

### Websocket (optional, no auth needed)
```
wss://<host>/ws/livestream/<id>/
```
Pushes `{"type": "chat_message", "message": {...}}`, `{"type": "chat_message_deleted", "message_id"}`, `{"type": "status_changed", "status"}`, `{"type": "recording_ready", "video_id"}`. Read-only: post chat via REST. If the socket can't connect, fall back to polling `GET /chat/?after=` and the stream detail — everything is available there too.

### Moderation
Moderators can use `POST /moderation/actions/` with:
- `{"action": "end_livestream", "livestream_id": "…", "note": "…"}` — ends the stream; the recording is kept **unpublished** for review; the creator is notified.
- `{"action": "remove_chat_message", "chat_message_id": "…"}`

Both appear in the audit log (`GET /moderation/actions/?livestream_id=`).

### New notification types
| Type | Triggered by |
|------|-------------|
| `livestream_started` | A channel you subscribe to went live (`data.livestream_id`) |
| `livestream_ended_by_moderator` | A moderator ended your stream |

### Livestream Endpoints Summary

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `GET` | `/api/v1/livestreams/` | Live and upcoming streams | — |
| `POST` | `/api/v1/livestreams/` | Create a stream | 🔒 verified creator |
| `GET` | `/api/v1/livestreams/me/` | My streams | 🔒 |
| `GET` | `/api/v1/livestreams/<id>/` | Stream detail | — |
| `PATCH` | `/api/v1/livestreams/<id>/` | Edit stream | 🔒 owner |
| `POST` | `/api/v1/livestreams/<id>/end/` | End stream | 🔒 owner |
| `POST` | `/api/v1/livestreams/<id>/cancel/` | Cancel stream | 🔒 owner |
| `POST` | `/api/v1/livestreams/<id>/heartbeat/` | Viewer heartbeat | — |
| `GET` | `/api/v1/livestreams/<id>/chat/` | Chat messages | — |
| `POST` | `/api/v1/livestreams/<id>/chat/` | Send chat message | 🔒 |
| `DELETE` | `/api/v1/livestreams/chat/<message_id>/` | Delete chat message | 🔒 |

---

## Privacy: email addresses

Email addresses are never shown to other users. Anywhere one user appears to another (comments, live chat, notifications) the API uses a **display name**: the profile's `full_name`, else the user's channel name, else `"Abia Stream user"`.

- Comment authors: `user` is `{id, display_name, full_name, avatar_url}` (no `email`).
- Channels: public responses have `owner_id` instead of `owner_email`. `owner_email` is only in the owner's own responses (`POST /channels/create/`, `GET/PATCH /channels/me/`).
