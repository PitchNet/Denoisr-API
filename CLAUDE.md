# CLAUDE.md — Denoisr API

Python FastAPI backend for Denoisr. Entry point: `app/main.py`.

## Commands

```bash
# Development (with hot reload)
uvicorn app.main:app --reload

# Production
uvicorn app.main:app --host 0.0.0.0 --port $PORT

# Generate VAPID key pair for push notifications
python3 -m py_vapid
```

## Environment variables

| Variable | Purpose |
|---|---|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase service role key |
| `SECRET_KEY` | HS256 JWT signing secret (default: `dev-secret`) |
| `CORS_ORIGINS` | Comma-separated allowed origins (default includes Vercel + localhost) |
| `APIFY_TOKEN` | Token for the Apify LinkedIn scraper actor |
| `GOOGLE_API_KEY` | Google AI API key (used for Gemini `gemma-4-31b-it`) |
| `VAPID_PUBLIC_KEY` | VAPID public key for Web Push |
| `VAPID_PRIVATE_KEY` | VAPID private key for Web Push |
| `VAPID_CLAIM_EMAIL` | Contact email in VAPID claims (default: `notifications@denoisr.com`) |
| `FETCH_BATCH_SIZE` | Default page size for feed queries (default: `10`) |
| `COOKIE_SECURE` | `Secure` flag on the auth cookie (default: `true`; set `false` for plain-HTTP local dev) |
| `COOKIE_SAMESITE` | `SameSite` attribute on the auth cookie (default: `none`, required for the cross-site Vercel↔Render setup; use `lax` if UI and API share a host locally) |
| `FRONTEND_BASE_URL` | Base URL used to build the password-reset link emailed to users (default: `http://localhost:5173`; set to the deployed UI origin in production) |
| `RESEND_API_KEY` | API key for [Resend](https://resend.com), used to send password-reset emails. **If unset, `/forgotPassword` skips email entirely and returns the reset token directly in its JSON response** so the UI can jump straight to the "set a new password" screen — see the security note under Auth below before relying on this in production |
| `RESEND_FROM_EMAIL` | `From` address for reset emails (default: `Denoisr <onboarding@resend.dev>`, Resend's shared sandbox sender — replace with a verified domain sender in production) |

## Architecture

### Auth

JWT (HS256), subject (`sub`) is the `people.id` UUID, 7-day lifetime (10080 minutes). The token is issued as an **httpOnly** cookie (`denoisr_auth_token`, see `app/auth_utils.py`) via `Set-Cookie` on `/LoginController/login` and `/LoginController/signup` — it is never returned in a JSON body, so browser-side JS (and therefore XSS) can't read it.

All protected endpoints depend on a local `get_current_user(request: Request)` that delegates to `auth_utils.get_current_user_row(request, supabase)`, which reads the token from the `denoisr_auth_token` cookie (falling back to an `Authorization: Bearer` header for non-browser clients) and looks up the user from `supabase.table("people")`. `POST /LoginController/logout` clears the cookie — call it on client-side logout, since JS can't clear an httpOnly cookie itself.

**Password reset:** `POST /LoginController/forgotPassword` and `POST /LoginController/resetPassword` (below) use a *stateless* reset token — a short-lived (30 min) JWT with `purpose: "password_reset"` and a `pwv` claim (last 16 chars of the current `passwordhash`), signed with the same `SECRET_KEY`. No new DB column or table: `auth_utils.decode_reset_token` re-checks `pwv` against the live `passwordhash` at consume time, so the token stops working the instant the password actually changes — that's what makes it single-use without a "used" flag. See `app/auth_utils.py` (`create_reset_token`/`decode_reset_token`) and `app/services/email_service.py` (delivery via Resend).

`forgot_password` branches on whether `RESEND_API_KEY` is set:
- **Set:** emails the reset link, response never contains the token. This is the secure mode — only whoever can read that inbox can complete the reset.
- **Unset (current default — no email provider configured):** the response body includes `token` directly, and `ForgotPasswordPage.tsx` redirects straight to `/reset-password?token=...` with no email step at all. **This is a deliberate but meaningful trade-off**: it means anyone who knows or guesses a registered email can reset that account's password with zero proof of inbox access — there is no email-based identity check happening in this mode. Acceptable for a demo/internal tool; set `RESEND_API_KEY` before this is exposed to users you don't trust with each other's accounts.

### Controllers

All routers are registered in `app/main.py`. Each file in `app/controllers/` is a self-contained FastAPI router.

#### `LoginController` — `/LoginController`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/signup` | No | Create account, insert profile + related rows, set the httpOnly JWT cookie, return `{ user }` (no token, no passwordhash) |
| POST | `/login` | No | Verify bcrypt password, set the httpOnly JWT cookie, return `{ user }` (no token) |
| POST | `/logout` | No | Clear the httpOnly JWT cookie |
| POST | `/forgotPassword` | No | Emails a reset link if `RESEND_API_KEY` is set (generic response either way, doesn't reveal whether the account exists); otherwise returns the reset token directly in the response so the UI can skip straight to the reset screen — see the security note above |
| POST | `/resetPassword` | No | Consumes a reset token (`{ token, newPassword }`) and updates `passwordhash` |
| GET | `/keepAlive` | No | Health-check ping |
| POST | `/linkedinImport` | No | Scrape LinkedIn via Apify → restructure with Gemini → return pre-filled profile JSON |
| GET | `/profile` | Yes | Legacy endpoint; returns current user info |

**LinkedIn import flow:** Apify actor `LpVuK3Zozwuipa5bp` scrapes the profile. Raw data is sent to `gemma-4-31b-it` with a structured prompt that outputs the Denoisr signup JSON format. The result is returned to the UI to pre-fill the signup form — no data is persisted by this endpoint.

#### `FeedController` — `/FeedController`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/fetchJobs` | Yes | Paginated + filtered job feed (cursor-based, excludes already-actioned jobs) |
| POST | `/fetchPeople` | Yes | Paginated + filtered people feed (excludes already-connected/sent users) |
| GET | `/getConnections` | Yes | All connected users with last-message preview, sorted by recent activity |
| POST | `/jobAction` | Yes | Record a job swipe: `action` = `"accepted"` or `"bookmark"` |
| POST | `/peopleAction` | Yes | Record a people swipe: see matching logic below |
| POST | `/sendMessage` | Yes | Send a message in a conversation (creates conversation if needed) |
| POST | `/getMessages` | Yes | Fetch messages for a conversation (by `conversationId` or `recipientId`) |
| GET | `/jobApplications` | Yes | All jobs the current user has swiped right on, with status |
| POST | `/InsertJobs` | No | Bulk-insert jobs with highlights, tags, sections (admin/seed use) |
| POST | `/InsertPeople` | No | Bulk-insert people profiles (admin/seed use) |

**Pagination:** Cursor-based on `(created_at DESC, id DESC)`. Pass `cursor` = last seen item's `id`; the query translates it to a timestamp+id comparison. Response includes `has_more`, `next_cursor`, `total_count`.

**Search:** Queries across `headline`, `subheadline`, `organization`, `location`, highlights, tags, and section items — all with `ilike` pattern matching.

**Matching logic (peopleAction):** When action is `"accepted"`:
1. Check if the other person has already sent a request to the current user (`user_people_actions` row with reversed user/people IDs).
2. If yes → both rows updated to `"connected"`, a `conversations` row created, both users added to `conversation_participants`, push notifications sent to both.
3. If no → record `"sent"` for the current user; wait for reciprocation.

#### `ProfileController` — `/ProfileController`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/getProfile` | Yes | Full profile including highlights, tags, sections, work experience, projects |
| POST | `/updateProfile` | Yes | Replace-all update (deletes + re-inserts all related rows) |
| POST | `/uploadImage` | Yes | Upload photo to ImgBB, return public URL |

**Image upload:** `service.py` (`UploadImageKey`) scrapes an ImgBB session auth token. The image is then POSTed directly to `https://imgbb.com/json` with that token. Returns the public image URL.

#### `CompanyController` — `/CompanyController`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/companyDetails` | Yes | Create or update company profile; links company to the current user |
| GET | `/getCompany` | Yes | Get current user's associated company |
| POST | `/jobDetails` | Yes | Create or update a job listing under the user's company |
| GET | `/companyJobs` | Yes | All jobs posted by the user's company |
| POST | `/jobApplicants` | Yes | People who swiped right on a specific job, with full profiles |
| GET | `/jobApplicantCounts` | Yes | Applicant count per job for the user's company |
| POST | `/jobApplicantStatus` | Yes | Update a candidate's status in the hiring pipeline; sends push notification |

**Applicant status pipeline:** `new` → `submitted` → `reviewing` → `shortlisted` → `messaged` → `hired` / `passed`

#### `NotificationController` — `/NotificationController`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/subscribe` | Yes | Register a Web Push subscription (upsert on `user_id, endpoint`) |
| POST | `/unsubscribe` | Yes | Remove a push subscription |
| GET | `/vapidPublicKey` | No | Return VAPID public key to the client |
| POST | `/testPush` | Yes | Send a test push to the current user |
| GET | `/getNotifications` | Yes | Paginated in-app notifications (cursor-based) |
| POST | `/markRead` | Yes | Mark specific or all notifications as read |
| GET | `/unreadCount` | Yes | Count of unread notifications |

**`send_push` helper** (importable by other controllers): persists a row to `notifications`, then sends Web Push via `pywebpush` to all device subscriptions for the user. Automatically cleans up expired subscriptions (HTTP 410/404 responses).

#### `SettingsController` — `/SettingsController`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/getSettings` | Yes | Notification + privacy preferences |
| POST | `/changePassword` | Yes | Verify current password, set a new one (min 8 chars) |
| POST | `/updateNotificationPreferences` | Yes | Update the three `notify_*` booleans |
| POST | `/updatePrivacySettings` | Yes | Update `profile_visible` / `allow_messages_from` |
| GET | `/exportData` | Yes | Returns the current user's full data as one JSON document: profile (minus `passwordhash`), highlights, tags, sections, work experience, projects, job/people actions, sent messages, notifications |
| POST | `/deleteAccount` | Yes | Verifies `password`, then permanently deletes the account and all rows owned by it (see below), clears the auth cookie |

**Account deletion** (`delete_account`) removes, in dependency order (children before parent, no FK cascade assumed): `message_reactions`, `messages` (where `sender_id`), `conversation_participants`, `user_job_actions`, `user_people_actions` (both `user_id` and `people_id` sides), `blocked_users` (both directions), `user_reports` (both directions), `notifications`, `push_subscriptions`, `people_section_items` → `people_sections`, `people_highlights`, `people_tags`, `people_work_experience`, `people_projects`, then the `people` row itself. **Deliberately left untouched:** any `companies`/`jobs` rows the user created — those can hold other people's data (applicants, teammates) and aren't solely this account's personal data, so deletion doesn't cascade into them.

### Services

`app/services/service.py` — `UploadImageKey()` scrapes a session token from ImgBB. Called by `ProfileController.uploadImage`.

### Helpers

`app/controllers/_helpers.py` — `api_error()` and `check_data()` for consistent error formatting. Not yet widely used across controllers (most use inline `raise HTTPException`).

## Database schema (Supabase / Postgres)

Tables inferred from queries — source of truth is `../Denoisr-DB/DDL/`.

| Table | Key columns |
|---|---|
| `people` | `id`, `emailaddress`, `passwordhash`, `headline`, `subheadline`, `organization`, `location`, `experience`, `salary`, `intro`, `photo`, `companyid`, `kind`, `name`, `currentrole` |
| `people_highlights` | `person_id`, `highlight` |
| `people_tags` | `person_id`, `tag` |
| `people_sections` | `id`, `person_id`, `title` |
| `people_section_items` | `section_id`, `item` |
| `people_work_experience` | `person_id`, `company`, `role`, `duration`, `description` |
| `people_projects` | `person_id`, `name`, `url`, `description` |
| `jobs` | `id`, `headline`, `subheadline`, `organization`, `location`, `experience`, `salary`, `intro`, `company_id` |
| `job_highlights` | `job_id`, `highlight` |
| `job_tags` | `job_id`, `tag` |
| `job_sections` | `id`, `job_id`, `title` |
| `job_section_items` | `section_id`, `item` |
| `companies` | `id`, `name`, `photo`, `website`, `size`, `address`, `description`, `phone`, `year_founded`, `tags`, `commitments` |
| `user_job_actions` | `user_id`, `job_id`, `action` (`"accepted"` / `"bookmark"`), `status` |
| `user_people_actions` | `user_id`, `people_id`, `action` (`"sent"` / `"connected"` / `"bookmark"`) |
| `conversations` | `id`, `updated_at` |
| `conversation_participants` | `conversation_id`, `user_id` |
| `messages` | `id`, `conversation_id`, `sender_id`, `content`, `created_at` |
| `push_subscriptions` | `id`, `user_id`, `endpoint`, `p256dh_key`, `auth_key` |
| `notifications` | `id`, `user_id`, `type`, `title`, `body`, `data`, `read`, `created_at` |

## Third-party integrations

| Service | Usage | Config |
|---|---|---|
| Supabase | Primary DB + realtime (UI side) | `SUPABASE_URL`, `SUPABASE_KEY` |
| Apify | LinkedIn profile scraping (actor `LpVuK3Zozwuipa5bp`) | `APIFY_TOKEN` |
| Google Gemini | Restructures LinkedIn JSON into Denoisr format (`gemma-4-31b-it`) | `GOOGLE_API_KEY` |
| ImgBB | Profile photo hosting | Session token scraped dynamically by `service.py` |
| Web Push (pywebpush) | Push notifications to browsers | `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` |
