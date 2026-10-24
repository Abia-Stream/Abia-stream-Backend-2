# Changelog

What changed in the backend, newest first. Endpoint details live in
[API DOCUMENTATION.md](API%20DOCUMENTATION.md); what the frontend has to build is in
[FRONTEND_INTEGRATION.md](FRONTEND_INTEGRATION.md).

---

## 2026-10-24: Manual ID review tools

- **Review checklist:** approving needs every item ticked (name matches, face matches, selfie shows the person holding the ID, not expired, readable, not edited). The answers are stored with the decision.
- **Rejection reasons** from a fixed list. The creator's notification and `latest_attempt.message` say exactly what to fix; `other` needs a note, which the creator sees.
- **Admins are notified** (`verification_submitted`) when a submission arrives or Smile flags one for review.
- **ID photos are deleted 30 days after the decision** (`VERIFICATION_DOCUMENT_RETENTION_DAYS`) by a daily job, or with `manage.py purge_verification_documents --apply`. The record of who was verified, by whom and when is kept. Attempts awaiting review are never touched.
- Database: `sql/013_verification_review.sql`.

---

## 2026-10-18: Identity verification rebuilt; email without a domain

- **ID verification works for the first time.** The old Smile Identity code used an endpoint, signature and job type that don't exist in Smile's API, so it could never have verified anyone (no user is verified in production, so nobody new could create a channel). Now:
  - **Smile ID v3 Document Verification** via Smile's Web SDK. The backend issues a session token bound to the user (`POST /verification/smile/session/`). Smile's webhook (`/verification/smile/callback/`) is signature-checked, but because Smile's signature doesn't cover the body, the verdict is always fetched from Smile's status API before anything changes. A user can only report their own job (`POST /verification/check/`).
  - **Manual review** as the fallback: the upload form now stores photos **privately** on Cloudinary (signed links for admins only; before, ID documents would have been public) and queues them for an admin (`GET /verification/review/`, `PATCH /verification/review/attempts/<id>/`).
  - Every attempt is recorded (`verification_attempts`), and each outcome is applied once: webhook retries don't send duplicate notifications, and an approved user is never downgraded.
  - Database: `sql/012_verification_attempts.sql`.
- **Email provider is configurable** (`EMAIL_PROVIDER`): `resend` or `brevo` (both need a verified domain), or `apps_script`: a Google Apps Script web app (`scripts/send_email.gs`) that sends from a Gmail account over HTTPS, with no domain needed and no problem with Render's free-plan SMTP block (about 100 recipients a day). Resending a code or a password reset now answers 503 with a clear message instead of a 500 when email fails.
- **Fix:** server-side video uploads with a rejected file returned 500 instead of the 400 explaining why (the view caught the email library's `ValidationError`).

---

## 2026-10-14: Production fixes (reported by the frontend)

- **ID verification no longer crashes.** The Smile Identity settings were commented out, so `POST /verification/submit/` returned 500. They are now read from `SMILE_IDENTITY_PARTNER_ID`, `SMILE_IDENTITY_API_KEY` and `SMILE_IDENTITY_ENVIRONMENT` (`sandbox` by default, `production` for real checks). Until the keys are set, the endpoint answers 503 with a clear message instead of uploading the documents.
- **`DEBUG` is off by default.** It used to fall back to on when unset; now it is on only if `DEBUG=True` is set explicitly.
- **Videos include `channel_slug` and `channel_name`**, fetched in the same query as the video, so lists don't make an extra query per video.
- **Password sign-up is all-or-nothing.** If the verification email can't be sent, no account is created and the API returns 503 (before, a half-created account blocked the email from registering again). Re-registering an unverified email now says to use "Resend code"; a verified email says to log in.

---
## 2026-10-11: Monetization (Paystack)

- **Tips** on videos, livestreams (announced live in chat) or creators.
- **Paid channel memberships** (monthly Paystack subscriptions) and a new **`members_only`** video visibility. `subscribers_only` is unchanged.
- **Ad revenue share:** admins enter each period's ad revenue; after the platform fee it's split by watch time on monetized videos.
- **Payouts** to verified Nigerian bank accounts.
- **Earnings ledger:** every balance change is one row; duplicate webhooks and retries can't credit twice; a failed payout is credited back.
- **Platform fee configurable** by admins (default 20%), fixed on each payment when it's made.
- Payments count only after Paystack confirms them server-side; webhooks must be signed.
- Creator dashboard `recent_earnings`, `monetization_enabled` and chart `revenue` are now real.
- Database: `sql/011_monetization.sql`. Needs `PAYSTACK_SECRET_KEY`, `PAYSTACK_PUBLIC_KEY`, `PAYSTACK_CALLBACK_URL`.

---

## 2026-10-11: Admin user management and share counting

- **Admins can appoint moderators and admins.** The user-management code existed but was never routed, so roles could only be changed in the database. New: `GET /admin/users/` (filter, search), `GET/PATCH /admin/users/<id>/`. Validated values, no changing your own role/status, and the active-admin rows are locked during a change so two admins can't demote each other at once and leave none.
- **Shares are counted.** `shares_count` existed but nothing increased it. New `POST /videos/<id>/share/`, counted once per viewer per video per 24 hours.

---

## 2026-10-09: Best-frame thumbnails for direct uploads

Direct uploads kept the frontend's frame-at-1-second thumbnail, so only server-side uploads got the best-frame one. Now frame thumbnails are upgraded to the best frame once Cloudinary has generated it (it answers "not ready" for up to a minute on larger videos, verified in production); the old thumbnail stays until then. Custom image thumbnails are never touched. `refresh_auto_thumbnails` backfills existing videos (dry run by default).

---

## 2026-10-09: Personalization groundwork (roadmap Stage 4)

Built so it switches on as real data arrives; **nothing changes for users until an experiment is turned on**.

- **Learned feed ranker.** Every For You page is logged with each item's ranking features; a nightly job trains a ranker on "shown → watched within 30 minutes" and activates it only if it beats the current hand-tuned order on recent held-out data by more than the measurement noise (checked: real signal activates 20/20 times, pure noise 0/20). It serves only viewers in the `feed_ranker` experiment (created **off**).
- **Up next** — `GET /videos/<id>/up-next/`: what viewers actually watched next, then related, same creator, For You.
- **Personalized search** — results nudged toward the viewer's categories and creators, in the `search_personalization` experiment (created **off**).
- **A/B results** — `GET /analytics/experiments/<key>/`: watch rate per arm, lift and a significance test.
- Database: `sql/010_personalization.sql`.
- Not built: personalized thumbnails (needs several thumbnails per video first) and reinforcement learning (large scale only).

**Data status at release:** 0 behaviour events, 0 recorded views, 7 watch-history rows. The ranker needs about 1,000 shown items and 50 watches before it can even be evaluated; the frontend must report views (`POST /playback/view/`) and events.

---

## 2026-10-09: Automatic moderation, upload limit, thumbnails ([#6](https://github.com/Abia-Stream/Abia-Stream-Backend/pull/6))

Roadmap Stage 2.

- **Automatic moderation.** Strong matches are held from the public until a moderator reviews them; weaker signals only go to the queue.
  - A re-upload of a **blocked** video (visual fingerprint) → new video status **`held`**, creator notified (`video_held`).
  - A copy of another creator's earlier video, or spam links / phone numbers / banned terms in video text or comments → queue entry, content stays up.
  - Live chat refuses links, phone numbers and banned terms.
  - Blocking a video also holds its existing copies.
  - Moderators approve held videos with the new `approve_video` action (`video_approved` notification).
- **Upload size limit (bug).** Our Cloudinary plan rejects videos over 100 MB, but the app allowed 500 MB–1 GB, so large uploads failed after the user waited. The real limit is now read from the account and enforced, and sent to the frontend as `max_file_size`.
- **Thumbnails.** New auto-thumbnails use the most interesting frame instead of the frame at 1 s.
- Database: `sql/009_auto_moderation.sql` — **applied to Supabase**.
- After deploy, run `python manage.py scan_videos` once to fingerprint videos uploaded before this release.

---

## 2026-10-09: Email privacy ([#4](https://github.com/Abia-Stream/Abia-Stream-Backend/pull/4))

Email addresses were visible to other users. Now:

| Where | Before | After |
|---|---|---|
| Comments (public) | author `email` | `display_name` (profile name → channel name → "Abia Stream user") |
| Channel detail and channel list (public) | `owner_email` | `owner_id` |
| Comment, reply, comment-like notifications | "jane@… commented…" | "Jane Obi commented…" |
| New-subscriber notifications | "jane@… subscribed…" | display name |

The owner's own channel responses (`/channels/me/`, create) keep `owner_email`.

## 2026-10-09: Docs and CORS ([#5](https://github.com/Abia-Stream/Abia-Stream-Backend/pull/5))

- This changelog and [FRONTEND_INTEGRATION.md](FRONTEND_INTEGRATION.md).
- Browsers may now send the `X-Session-Id` header (it was missing from CORS, so preflight requests failed).

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
| Run `python manage.py scan_videos` once after #6 deploys (fingerprints for older videos) | Production shell |
| View-log partitions for 2028+ (automatic once Celery runs, else `python manage.py ensure_view_log_partitions --months-ahead 14` before Dec 2027) | — |
