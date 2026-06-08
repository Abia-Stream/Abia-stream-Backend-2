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
6. [Enums Reference](#enums-reference)
7. [Error Responses](#error-responses)
8. [Status Codes](#status-codes)

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

> Response is identical whether the email exists or not.

---

### Verify Reset OTP

Validates the password reset OTP before allowing the password change. Optional but recommended for better UX.

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

Resets the user's password. OTP is re-verified at this step regardless of whether `/verify-reset-otp/` was called. Also clears any active account lockout.

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
| `400` | Invalid request |

---

## Token Management

### Refresh Access Token

Returns a new short-lived access token using a valid refresh token. The old refresh token is blacklisted and a new one is issued.

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

**Error Responses**

| Status | Detail |
|--------|--------|
| `401` | Authentication credentials were not provided |
| `404` | No Profile matches the given query |

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
    "instagram": "https://instagram.com/johndoe",
    "youtube": "https://youtube.com/@johndoe"
  }
}
```

**Validation Rules**
- `social_links` — must be a JSON object if provided
- `date_of_birth` — must be a past date

**Success Response** `200 OK`

Returns the full updated profile object (same shape as Get My Profile).

**Error Responses**

| Status | Detail |
|--------|--------|
| `400` | Validation error on one or more fields |
| `401` | Authentication credentials were not provided |
| `404` | No Profile matches the given query |

---

### Get Public Profile

Returns any user's public profile by their `user_id`.

**Endpoint**
```
GET /profile/<user_id>/
```

**Example**
```
GET /profile/6b21af05-dd8f-4e06-affd-ccb2d983ceae/
```

**Success Response** `200 OK`

Returns the full profile object (same shape as Get My Profile).

**Error Responses**

| Status | Detail |
|--------|--------|
| `404` | No Profile matches the given query |

---

## Enums Reference

### `user_role`

| Value | Description |
|-------|-------------|
| `viewer` | Default role for new users |
| `creator` | Content creator with upload access |
| `moderator` | Content management access |
| `admin` | Full admin access |

### `user_status`

| Value | Description |
|-------|-------------|
| `pending_verification` | Newly registered, email not yet verified |
| `active` | Email verified, can log in |
| `suspended` | Temporarily restricted |
| `banned` | Permanently restricted |

---

## Error Responses

All error responses follow this format:

```json
{
  "detail": "Human-readable error message."
}
```

Validation errors (field-level) follow this format:

```json
{
  "field_name": [
    "Error message for this field."
  ]
}
```

---

## Status Codes

| Code | Meaning |
|------|---------|
| `200` | OK — request succeeded |
| `201` | Created — resource created successfully |
| `400` | Bad Request — validation error or invalid input |
| `401` | Unauthorized — invalid or missing token |
| `403` | Forbidden — account not active, locked, suspended, or banned |
| `404` | Not Found — resource does not exist |
| `500` | Internal Server Error — unexpected server error |

---

## Full Flow Summary

```
Registration & Verification:
1. POST /auth/register/          → account created, OTP sent, profile auto-created
2. POST /auth/verify-email/      → status promoted to active
3. POST /auth/login/             → receive access + refresh tokens

Token Management:
4. POST /auth/token/refresh/     → get new access token (every 30 mins)
5. POST /auth/logout/            → blacklist refresh token

Password Reset:
1. POST /auth/forgot-password/   → OTP sent to email
2. POST /auth/verify-reset-otp/ → confirm OTP (optional UI step)
3. POST /auth/reset-password/    → submit new password with OTP

Profiles:
GET  /profile/me/                → get own profile (🔒)
PATCH /profile/me/               → update own profile (🔒)
GET  /profile/<user_id>/         → view any public profile
```

---

## Using the Access Token

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

> Never share or expose your JWT tokens. Use Postman environment variables (`{{access_token}}`) to keep them secure.

---

## Postman Quick Setup

1. Environment: `Abia-Stream-Dev`
2. Variable: `base_url` = `http://127.0.0.1:8000/api`
3. Add to Login request **Scripts → Post-response**:

```javascript
if (pm.response.code === 200) {
    const res = pm.response.json();
    pm.environment.set("access_token", res.access);
    pm.environment.set("refresh_token", res.refresh);
}
```

4. All protected requests → Authorization → Bearer Token → `{{access_token}}`

---

*Last updated: June 2026*