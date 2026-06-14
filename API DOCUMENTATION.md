# Abia Stream API Documentation

**Version:** 1.0.0  
**Base URL:** `http://127.0.0.1:8000/api` (development) · `https://api.abiastream.com/api` (production)  
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
9. [Enums Reference](#enums-reference)
10. [Error Responses](#error-responses)
11. [Status Codes](#status-codes)

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
  "email": "user@example.com",
  "password": "strongpassword123"
}
```

**Validation Rules**
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
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "user@example.com",
    "role": "viewer"
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
2. Variable: `base_url` = `https://abia-stream-backend.onrender.com/api/`
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