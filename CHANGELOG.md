# Changelog

What changed in the backend, newest first. Endpoint details live in
[API DOCUMENTATION.md](API%20DOCUMENTATION.md); what the frontend has to build is in
[FRONTEND_INTEGRATION.md](FRONTEND_INTEGRATION.md).

---

## Pending: Email privacy ([#4](https://github.com/Abia-Stream/Abia-Stream-Backend/pull/4), not merged yet)

Email addresses were visible to other users. Once #4 is merged:

| Where | Before | After |
|---|---|---|
| Comments (public) | author `email` | `display_name` (profile name → channel name → "Abia Stream user") |
| Channel detail and channel list (public) | `owner_email` | `owner_id` |
| Comment, reply, comment-like notifications | "jane@… commented…" | "Jane Obi commented…" |
| New-subscriber notifications | "jane@… subscribed…" | display name |

The owner's own channel responses (`/channels/me/`, create) keep `owner_email`.
**Breaking for the frontend** — coordinate before merging.

---

## 2026-10-07: Livestreaming ([#3](https://github.com/Abia-Stream/Abia-Stream-Backend/pull/3))

- Verified creators with a channel can create livestreams and broadcast from OBS or any RTMP encoder.
  Runs on Cloudinary Live Streaming (already enabled on our Cloudinary account).
- Streams go live automatically when the encoder connects and end when it stops (2-minute reconnect grace, 4-hour max).
- Viewers watch over HLS; live viewer counts via heartbeats; subscribers notified when a channel goes live.
- Recordings become normal videos on the channel when a stream ends (unpublished by default, or published automatically).
- Live chat: REST (post / poll / delete) plus a read-only websocket `ws/livestream/<id>/`.
- Moderators can end a stream (recording kept unpublished) and remove chat messages; both audited.
- Database: `sql/008_livestreaming.sql` — **applied to Supabase**.

---

## 2026-10-07: Discovery, delivery, moderation, analytics ([#1](https://github.com/Abia-Stream/Abia-Stream-Backend/pull/1))

### New features
- **Search** `GET /videos/search/?q=` — full-text over title and description.
- **Trending** `GET /videos/trending/` — ranked by completed views, not raw clicks.
- **For You feed** `GET /videos/feed/` — personalised (related videos, subscriptions, favourite categories, trending, fresh); works signed out.
- **Related videos** `GET /videos/<id>/related/` — "people who watched this also watched", rebuilt nightly.
- **Behaviour events** `POST /events/` and **A/B experiments** `GET /experiments/variants/`.
- **Adaptive streaming** — every video now has `streaming_url` (HLS, multiple qualities). Verified on a real video.
- **Signed delivery** — private, unlisted and subscribers-only videos are only reachable through signed links given to viewers who pass the access check. Public videos unchanged.
- **Reporting and moderation** — users report videos/comments; moderators get a queue, actions (block/restore video, remove/restore comment, suspend user, dismiss) and an audit log. The existing one-click report button now feeds the queue.
- **Admin analytics** — platform overview, daily activity, top videos, search insights (incl. zero-result searches).
- **Creator dashboard** — `new_subscribers_last_28_days` is now real (was always 0).

### Bugs fixed
- **View recording was failing in production since February 2026.** Only a January partition existed for `view_logs`, so every view insert failed (the table had 0 rows). Partitions now exist through December 2027.
- Video create/save would have failed after merge (generated search column written by Django).
- Creating experiments always failed (NULL written into NOT NULL columns).
- The creator profile `total_views` counter (added on `main`) never incremented for profiles created by Django; it is now also de-duplicated like video view counts.
- The Cloudinary webhook accepted unsigned requests; signatures are now checked (logging mode by default).

### Infrastructure
- **Celery** configured with scheduled jobs: view-log partition upkeep (daily), related-videos rebuild (nightly), livestream sync (every minute). The API works without a worker running; these jobs just pause.
- **Test suite** (118 tests) against a local copy of the production schema. Tests refuse to run against anything but a local database and never call Cloudinary.
- Database scripts `sql/005`–`007` — **applied to Supabase**.

---

## Operations still open

| Item | Needs |
|---|---|
| Run a Celery worker (`celery -A abiastream worker -B`) + Redis | Render access |
| Production start command `daphne abiastream.asgi:application` (websockets don't work under gunicorn) | Render access |
| Set `CLOUDINARY_WEBHOOK_VERIFY=enforce` after checking logs for signature errors | Render access |
| First real livestream from OBS to confirm going live → ending → recording | A verified creator account |
| CI: GitHub Actions doesn't start runs on the org | Org admin (Actions billing / minutes) |
| Rotate the Supabase database password (a fragment appeared in local tool output) | Supabase access |
| View-log partitions for 2028+ (automatic once Celery runs, else `python manage.py ensure_view_log_partitions --months-ahead 14` before Dec 2027) | — |
