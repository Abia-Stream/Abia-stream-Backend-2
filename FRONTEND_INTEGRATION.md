# Frontend Integration Guide

What the frontend needs to build or change to use the new backend features.
Ordered by priority. Full request/response details: [API DOCUMENTATION.md](API%20DOCUMENTATION.md).
What changed and why: [CHANGELOG.md](CHANGELOG.md).

Base URL: `https://abia-stream-backend.onrender.com/api/v1` · 🔒 = needs `Authorization: Bearer <access>`

**Nothing below is required to keep the current app working** except item 1 (when PR #4 merges) — every
other change is additive.

---

## 1. Required: stop reading other users' emails (live since backend PR #4)

| Where | Stop using | Use instead |
|---|---|---|
| Comment author | `comment.user.email` | `comment.user.display_name` (also `full_name`, `avatar_url`) |
| Public channel page / channel list | `channel.owner_email` | `channel.owner_id` (and `channel_name` for display) |

`owner_email` is still present on the owner's own `/channels/me/` and create responses.
Agree a date with the backend so #4 merges when this frontend change is live.

---

## 2. Video player: adaptive streaming

Every video object now has **`streaming_url`** (HLS `.m3u8`, several qualities). Prefer it over `cloudinary_url` (single MP4), which stays as a fallback.

```js
import Hls from 'hls.js';

function attach(videoEl, video) {
  const src = video.streaming_url;
  if (src && Hls.isSupported()) {
    const hls = new Hls();
    hls.loadSource(src);
    hls.attachMedia(videoEl);
  } else if (src && videoEl.canPlayType('application/vnd.apple.mpegurl')) {
    videoEl.src = src;                       // Safari / iOS: native HLS
  } else {
    videoEl.src = video.cloudinary_url;      // fallback MP4
  }
}
```

`streaming_url` is `null` for drafts that haven't been uploaded yet.

**Private / unlisted / subscribers-only videos:** the URLs come back **signed** (`…/authenticated/s--…--/…`). Use them exactly as returned; don't build Cloudinary URLs by hand, and re-fetch the video rather than caching URLs for long. If a URL field is `null`, the viewer isn't allowed to watch.

---

## 3. Uploads: private videos (small change)

When uploading **directly to Cloudinary**, pass the intended visibility when asking for signed params:

```
GET /videos/upload/signed-params/?visibility=private      🔒
```

If the response contains **`"type": "authenticated"`**, add `type` to the Cloudinary upload form along with the other fields — the signature covers it and Cloudinary rejects the upload without it. For `public` there is no `type` and nothing changes.

Older clients that don't do this still work (the backend moves the file afterwards), but the video is briefly reachable by its plain URL.

---

## 4. Home page: For You feed

```
GET /videos/feed/?page=1&page_size=8        (auth optional — personalised when signed in)
```

Paginated like other lists. Each video has an extra **`feed_reason`** for UI copy:

| `feed_reason` | Suggested label |
|---|---|
| `related` | "Because you watched …" |
| `subscription` | "New from a channel you follow" |
| `category` | "Popular in a category you like" |
| `trending` | "Trending" |
| `fresh` | "New" |

Also available: `GET /videos/trending/?days=7` (array, max 50) and
**`GET /videos/<id>/up-next/?limit=10`** for the "Up next" rail on the watch page — it always returns
something (what viewers watched next → related → same creator → For You), each with `up_next_reason`.
Prefer it over `GET /videos/<id>/related/`, which is empty until enough watch history exists.

**Recording views matters more than anything else on this list:** call `POST /playback/view/`
(with `session_id`) when playback starts. Trending, related, up next and the learned ranker are all
built from these views, and production currently has none.

---

## 5. Search

```
GET /videos/search/?q=<text>&page=1
```
Paginated. `400` if `q` is empty — don't call it with an empty box.

---

## 6. Behaviour events (powers recommendations and search ranking)

Generate a **session id** (UUID) per browser session, keep it in `sessionStorage`, and send it as header `X-Session-Id` on every API call. Buffer events and flush every ~10 s or on page hide:

```
POST /events/          (auth optional, max 100 events per request)
{"events": [
  {"event_type": "impression", "session_id": "<uuid>", "video_id": "<uuid>"},
  {"event_type": "video_click", "session_id": "<uuid>", "video_id": "<uuid>", "payload": {"source": "feed", "position": 3}},
  {"event_type": "search_result_click", "session_id": "<uuid>", "video_id": "<uuid>", "payload": {"query": "jollof", "position": 1}},
  {"event_type": "play", "session_id": "<uuid>", "video_id": "<uuid>", "payload": {"position": 0}}
]}
```

Event types: `impression`, `video_click`, `search_result_click`, `play`, `pause`, `seek`, `skip`, `complete`. (`search` is logged by the server.)

---

## 7. A/B experiments

```
GET /experiments/variants/      → {"feed_v2": "treatment", ...}
```
Call once on app load (with `X-Session-Id` when signed out) and branch UI on the returned variants. Missing key = show the default (control).

---

## 8. Reporting content

Add a **Report** option on videos and comments with a reason picker:

```
POST /reports/      🔒
{"video_id": "<uuid>", "reason": "spam", "details": "optional"}
   or {"comment_id": "<uuid>", ...}
```

Reasons: `spam`, `harassment`, `hate`, `violence`, `sexual`, `child_safety`, `copyright`, `misinformation`, `other`.
`201` new · `200` already reported (show "Already reported") · `400` own content.
`GET /reports/` 🔒 lists the user's reports and their status.

---

## 9. Livestreaming (new pages)

### Creator: "Go live"
Only for **verified creators with a channel** (others get `403` with a reason — show it).

```
POST /livestreams/      🔒
{"title": "...", "description": "...", "scheduled_start_time": "2026-10-09T19:00:00Z",
 "thumbnail_url": "...", "chat_enabled": true, "save_recording": true, "publish_recording": false}
```
Show the returned **`rtmp_url`** and **`stream_key`** with copy buttons and OBS instructions:
*Settings → Stream → Service: Custom → Server = `rtmp_url`, Stream Key = `stream_key`*.
Mask the key by default ("Show" toggle) — anyone with it can broadcast.

There's **no Start button**: the stream goes live when OBS connects. Show status by polling `GET /livestreams/<id>/` every ~10 s.
Controls: `POST /livestreams/<id>/end/`, `POST /livestreams/<id>/cancel/` (before live), `PATCH /livestreams/<id>/` (edit).
"My streams": `GET /livestreams/me/`. After a stream ends with recording on, the video appears in *My Videos* (ready to publish) within a few minutes.

### Viewer: watch page
```
GET /livestreams/<id>/          poll every ~10 s (or use the websocket)
```
- `status = scheduled` → "Starts at …" + countdown from `scheduled_start_time`.
- `status = live` → play `playback_url` with hls.js (as in §2), show `viewer_count`.
- `status = ended` → "Stream ended"; if `recording_video_id` is set, link to that video.

While the player is open, send a heartbeat every **20 s** (same session id as §6):
```
POST /livestreams/<id>/heartbeat/   {"session_id": "<uuid>"}   → {"status": "live", "viewer_count": 12}
```

### Chat
```
GET    /livestreams/<id>/chat/                       last 100, oldest first
GET    /livestreams/<id>/chat/?after=<last_id>       newer messages (poll every 3–5 s)
POST   /livestreams/<id>/chat/   {"content": "..."}   🔒 1–500 chars, 20/min
DELETE /livestreams/chat/<message_id>/               🔒 own message, or any message if you own the stream
```
Message: `{id, livestream_id, user: {id, display_name, avatar_url}, content, created_at}`.
Hide the input if `chat_enabled` is false or the stream isn't scheduled/live.

**Websocket (optional, recommended):** `wss://<host>/ws/livestream/<id>/` pushes
`chat_message`, `chat_message_deleted`, `status_changed`, `recording_ready`. Keep the polling fallback:
websockets don't work in production yet (pending a server start-command change).

### Discover
`GET /livestreams/` → live now (most viewers first), then upcoming. Filter with `?status=live|scheduled|ended`.

### Notifications
New types to render: `livestream_started` (link to `data.livestream_id`), `livestream_ended_by_moderator`.

---

## 10. Moderator tools (users with role `moderator` or `admin`)

```
GET  /moderation/queue/?target_type=video|comment       reported items, most-reported first
GET  /moderation/reports/?video_id=… | ?comment_id=…     the individual reports
POST /moderation/actions/   {"action": "...", "<target>_id": "...", "note": "shown to the creator"}
GET  /moderation/actions/                                audit log
```

| Action | Target field |
|---|---|
| `block_video`, `restore_video` | `video_id` |
| `remove_comment`, `restore_comment` | `comment_id` |
| `suspend_user`, `unsuspend_user` | `user_id` |
| `dismiss` (close reports, no change) | `video_id` or `comment_id` |
| `end_livestream` | `livestream_id` |
| `remove_chat_message` | `chat_message_id` |

A `400` comes with a readable `detail` (e.g. "Video is already blocked") — show it.
New notification types for creators: `video_blocked`, `video_restored`, `comment_removed`.
Blocked videos show `status: "blocked"` in the creator's *My Videos* and can't be edited or republished.

---

## 11. Admin analytics (role `admin`)

`period` = `1d`, `7d`, `28d`, `90d`.

| Endpoint | Use for |
|---|---|
| `GET /analytics/overview/?period=28d` | KPI tiles: users, uploads, views, watch hours, completion rate, % change, open reports |
| `GET /analytics/daily/?period=28d` | Line charts (views, watch hours, new users, uploads per day) |
| `GET /analytics/top-videos/?period=7d` | Top videos table |
| `GET /analytics/search/?period=7d` | Top searches and **zero-result searches** (content gaps) |

---

## 12. Videos under review (`held`) and upload size

- A new video **status `held`** means an automatic check found a likely re-upload of a blocked video and moderators are reviewing it. Show it in *My Videos* as "Under review". The creator can edit title/description but not the status. Publishing can return `200` with `status: "held"` instead of `"published"` — show "Your video is being reviewed" rather than an error.
- New notifications: `video_held`, `video_approved`.
- `GET /videos/upload/signed-params/` returns **`max_file_size`** (bytes) — currently **100 MB**. Check the file before uploading and tell the user if it's too big; Cloudinary rejects larger files after the whole upload.
- Live chat can now return `400` "Links, phone numbers and blocked words aren't allowed in chat." — show it next to the input.
- Moderators: queue rows have `automatic_signals` (what the automatic check matched, e.g. `{"signal": "reupload_of_blocked", "matched_video_id": "…", "similarity": 1.0}`) and there's a new action `approve_video` for held videos.

---

## 13. Share button and admin user management

- **Share button:** after the viewer shares (share sheet opened or link copied), call
  `POST /videos/<id>/share/` with `{"destination": "whatsapp" | "copy_link" | …}` and update the count from
  the response's `shares_count`.
- **Admin › Users** (role `admin`): `GET /admin/users/?q=&role=&status=` to list/search, and
  `PATCH /admin/users/<id>/` with `{"role": "moderator"}` or `{"status": "suspended"}`. Show the `detail` of a
  `400` (e.g. trying to change your own role). New notification type: `role_changed`.

---

## 14. Monetization

Amounts are **kobo** (₦500 = `50000`). Full details: API DOCUMENTATION.md, Monetization section.

- **Tip button** (video page, live page, channel): `POST /monetization/tips/`, then open `authorization_url`
  (or Paystack Popup with `access_code` + `public_key`). On your Paystack callback page call
  `GET /monetization/payments/<reference>/` and show success, pending or failed. Live tips arrive on the
  stream websocket as `type: "tip"`; show them in chat.
- **Join channel**: `GET /channels/<slug>/membership/` for the price and current membership;
  `POST .../membership/join/` uses the same checkout flow. "My memberships" with cancel.
- **Members-only videos**: visibility `members_only` in the upload/edit form; a non-member gets `403`,
  so show "Join to watch".
- **Creator > Monetization**: set the membership price (`PUT /channels/me/membership/`), earnings page
  (`GET /monetization/earnings/`), bank account (`GET /monetization/payouts/banks/`,
  `PUT /monetization/payouts/account/`), withdraw (`POST /monetization/payouts/`).
- **Admin**: fee settings, monetization overview, ad revenue periods (create, review the preview, distribute).
- New notifications: `tip_received`, `new_member`, `membership_payment`, `payout_paid`, `payout_failed`, `ad_share_credited`.

---

## 15. Small things

- **Videos carry their channel:** every video object now has `channel_slug` and `channel_name` (null if the creator has no channel). Link to `/channels/<channel_slug>/` from video cards.
- **Sign-up errors:** `POST /auth/register/` needs `email`, `password` (8+ chars) and `full_name`. Show the field messages from a `400`: an email that is registered but unverified tells the user to use "Resend code" (`POST /auth/resend-otp/`), and a verified one tells them to log in. A `503` means the verification email couldn't be sent and **no account was created**, so show `detail` and let them retry.
- Creator dashboard: `new_subscribers_last_28_days` now has real numbers.
- `POST /playback/view/` response now includes `counted` (false for a repeat view in the same session within 30 min). Send `session_id` so de-duplication works.
- Rate limits: reports 30/hour, chat 20/min, heartbeats 10/min, events 120 requests/min. Handle `429` quietly.

## 16. Identity verification (rebuilt)

Creating a channel needs an approved ID verification, and **nobody can be verified today**: the old Smile code
never worked. There are now two paths. Ask `GET /verification/config/` which ones are available:

```json
{"smile_enabled": true, "manual_review_enabled": true,
 "smile": {"partner_id": "…", "environment": "sandbox", "product": "doc_verification",
           "callback_url": "https://…/api/v1/verification/smile/callback/"},
 "manual_id_types": ["IDENTITY_CARD", "DRIVERS_LICENSE", "PASSPORT", "VOTER_ID", "RESIDENT_ID"]}
```

**A. Automatic (Smile ID), when `smile_enabled` is true.** Smile needs a live camera capture (selfie plus
liveness frames), so use their hosted Web SDK rather than a file upload:

1. Load `<script src="https://cdn.usesmileid.com/inline/v12/js/script.min.js"></script>`.
2. `POST /verification/smile/session/` returns `{token, partner_id, environment, product, callback_url}`.
   Get a fresh token for each attempt (they last 15 minutes).
3. Call `window.SmileIdentity({token, product, callback_url, environment, partner_details: {partner_id,
   name: 'Abia Stream', logo_url, policy_url, theme_color}, onResult})`. All five `partner_details` fields are
   required. The page must be HTTPS so the browser allows the camera.
4. In `onResult`, if Smile gives you a `job_id`, send it to `POST /verification/check/` with
   `{"job_id": "job_…"}` and show the returned `verification_status`. The final answer also arrives by webhook,
   so `GET /verification/status/` will catch up even if this step is skipped.

Results: `approved` (can create a channel), `pending` (still processing, or Smile asked for a human review),
`rejected` (may try again), or back to `not_submitted` if Smile couldn't process the photos (also try again).

**B. Manual review, always available.** This is the existing form: `POST /verification/submit/` (multipart)
with `id_document`, `selfie` and `id_type`, using one of `manual_id_types`. The old `NATIONAL_ID` and
`VOTERS_ID` names still work. The photos are stored privately, the response is `202` with `pending`, and an
admin decides. Use this when `smile_enabled` is false, or as a "Can't use your camera?" option.

`GET /verification/status/` now also returns `latest_attempt` (`method`, `status`, `message`). New notification:
`verification_error`.

**Admin › Verification** (role `admin`): `GET /verification/review/` lists attempts awaiting a decision, oldest
first, with private photo links (`document_url`, `selfie_url`; for Smile attempts, see the photos in the Smile
portal). Decide with `PATCH /verification/review/attempts/<attempt_id>/` and
`{"decision": "approve" | "reject", "note": "…"}`.

---

## Checklist

- [ ] §1 Comments/channels: `display_name`, `owner_id` (**before backend #4 merges**)
- [ ] §2 HLS player with `streaming_url`
- [ ] §3 `?visibility=` + `type` on direct uploads
- [ ] §4 For You feed on home, trending, `up-next` rail; **`POST /playback/view/` on play**
- [ ] §5 Search
- [ ] §6 Session id header + events
- [ ] §7 Experiment variants
- [ ] §8 Report button
- [ ] §9 Go live, watch page, heartbeat, chat, live discovery
- [ ] §10 Moderator queue
- [ ] §11 Admin analytics
- [ ] §12 "Under review" for `held` videos; size check with `max_file_size`; chat 400 message; `approve_video` in moderator UI
- [ ] §13 Share button → `POST /videos/<id>/share/`; Admin › Users screen
- [ ] §14 Tips, memberships, members-only, creator earnings/payouts, admin monetization
- [ ] §15 New notification types; `session_id` on view recording
- [ ] §16 Identity verification: Smile Web SDK flow, manual form fallback, Admin › Verification queue
