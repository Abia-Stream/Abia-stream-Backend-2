# Abia Stream API Documentation

**Version:** 1.0.0  
**Base URL:** `http://127.0.0.1:8000/api` (development) · `https://api.abiastream.com/api` (production)  
**Authentication:** Bearer JWT Token

---

## Table of Contents

1. [Authentication](#authentication)
2. [Email Verification](#email-verification)
3. [Token Management](#token-management)
4. [Password Reset](#password-reset)
5. [Enums Reference](#enums-reference)
6. [Error Responses](#error-responses)
7. [Status Codes](#status-codes)

---

## Authentication

### Register

Creates a new user account with status `pending_verification` and sends a 6-digit OTP to the provided email.

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

> **Note:** After registration, the user's status is `pending_verification`. They must verify their email before logging in.

---

## Email Verification

### Verify Email

Verifies the user's email using the 6-digit OTP sent during registration. On success, the user's status is updated from `pending_verification` to `active`.

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

> **Note:** Response is identical whether the email exists or not to prevent email enumeration.

**Error Responses**

| Status | Detail |
|--------|--------|
| `400` | Email already verified |

---


### Login

Authenticates a user and returns JWT access and refresh tokens. User must have verified their email and have an `active` status.

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

> **Note:** Response is identical whether the email exists or not.

---

### Verify Reset OTP

Validates the password reset OTP before allowing the password change. This step is optional but recommended for a better UX — it allows the frontend to confirm the OTP is valid before asking the user to type a new password.

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

Resets the user's password. The OTP is re-verified at this step regardless of whether `/verify-reset-otp/` was called. Also clears any active account lockout.

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


## Enums Reference

### `user_role`

| Value | Description |
|-------|-------------|
| `viewer` | Default role for new users |
| `creator` | Content creator with upload access |
| `moderator` | Moderator with content management access |
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

**Example:**
```json
{
  "email": ["Enter a valid email address."],
  "password": ["This field may not be blank."]
}
```

---

## Status Codes

| Code | Meaning |
|------|---------|
| `200` | OK — request succeeded |
| `201` | Created — resource created successfully |
| `400` | Bad Request — validation error or invalid input |
| `401` | Unauthorized — invalid credentials or token |
| `403` | Forbidden — account not active, locked, suspended, or banned |
| `404` | Not Found — resource does not exist |
| `500` | Internal Server Error — unexpected server error |

---

## Full Auth Flow

```
Registration & Verification:
1. POST /auth/register/          → account created (status: pending_verification), OTP sent
2. POST /auth/verify-email/      → OTP verified, status promoted to active
3. POST /auth/login/             → receive access + refresh tokens
4. POST /auth/token/refresh/     → get new access token when expired
5. POST /auth/logout/            → blacklist refresh token

Password Reset:
1. POST /auth/forgot-password/   → OTP sent to email
2. POST /auth/verify-reset-otp/ → confirm OTP is valid (optional UI step)
3. POST /auth/reset-password/    → submit new password with OTP
```

---

## Using the Access Token

Include the access token in the `Authorization` header for all protected endpoints:

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

---

*Last updated: June 2026*