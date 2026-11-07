# API endpoints

All routes are prefixed with `/api/`. Auth is JWT bearer (`Authorization: Bearer <access>`) unless noted. Full interactive schema: `/api/docs/`.

Endpoints marked "paginated" return `{"count", "next", "previous", "results"}` and accept `?page=` and `?page_size=` (default 20, max 100).

## Users (`/api/users/`)

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `register/` | none | Register with `phone` + password |
| POST | `login/` | none | Get access/refresh tokens |
| POST | `token/refresh/` | none | Refresh an access token |
| POST | `logout/` | user | Revoke all of the current user's JWTs |
| GET | `me/` | user | Get own profile |
| PATCH | `me/` | user | Update own `full_name`/`email` |
| POST | `change-password/` | user | Change password; revokes all sessions |
| POST | `password-reset/request/` | none | Send a 6-digit SMS code (valid 2 min, resend cooldown 60s; 204 even for unknown phones, 502 if the SMS provider fails) |
| POST | `password-reset/verify/` | none | `phone` + `code` → single-use `reset_token` (10 min). 5 wrong codes burn the code (429) |
| POST | `password-reset/confirm/` | none | `reset_token` + `new_password` + `confirm_password`; revokes all sessions |
| GET | `admin/` | admin | List/search users, paginated (`?search=` matches phone, email, or full name) |
| GET/PATCH | `admin/<user_id>/` | admin | Get user / activate-deactivate / grant-revoke admin (`is_staff`) role — revoking either also revokes sessions |

## Courses (`/api/courses/`)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `` | none | List published courses (instructor, category, level, cover image, benefits, etc.) |
| GET | `<course_id>/` | none | Published course detail + video list (title/description/duration only, no keys) |
| GET | `my-enrollments/` | user | Courses the current user currently has active (non-expired) access to |
| GET | `videos/<video_id>/key/` | user | Issue decryption key + presigned download URL (enrollment-gated, expiry-checked) |
| GET/POST | `admin/` | admin | List / create courses |
| GET/PATCH/DELETE | `admin/<course_id>/` | admin | Get / update / delete a course |
| GET/POST | `admin/<course_id>/videos/` | admin | List a course's videos / upload a new one (title, description, order, duration) |
| DELETE | `admin/videos/<video_id>/` | admin | Delete a video |
| POST | `admin/<course_id>/enrollments/<user_id>/` | admin | Grant a user access to a course (optional `expires_at`, defaults to the course's `access_duration_days`) |
| DELETE | `admin/<course_id>/enrollments/<user_id>/` | admin | Revoke a user's access to a course |
| POST | `admin/<course_id>/enrollments/<user_id>/renew/` | admin | Extend/renew a user's existing access |
| GET | `admin/users/<user_id>/enrollments/` | admin | A user's active and expired enrollments (for the admin user-detail page) |

Course fields: `title`, `slug`, `description`, `short_description`, `price`, `instructor_name`, `category`, `level` (`beginner`/`intermediate`/`advanced`), `cover_image_url`, `benefits` (one per line), `access_duration_days` (blank = lifetime).

Video fields: `title`, `description`, `order`, `duration_seconds`, `file_size_bytes` (auto-computed on upload), `status`.

## Purchases (`/api/purchases/`)

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `` | user | Start a ZarinPal payment for a course |
| GET | `callback/` | none | ZarinPal payment callback (`purchase_id`, `Authority`, `Status` query params documented in Swagger) |
| GET | `my/` | user | Current user's purchase history (`id`, `course_id`, `course_title`, ...) |
| GET | `admin/` | admin | List all purchases, paginated (`user_id`, `user_email`, `user_name`, `user_phone`, `course_id`, `course_title`, ...) |
| GET | `admin/reports/financial/` | admin | Revenue report; `by_course` is a typed list of `{course_id, course_title, revenue, sales}` |
| GET | `admin/users/<user_id>/` | admin | A specific user's purchase/transaction history, paginated |

## SMS (`/api/sms/`)

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `admin/send/` | admin | `message` + either `user_ids: [..]` (one or many) or `send_to_all: true` (all active users). Sent immediately (3 attempts per batch); 200 `{recipients}`, or 502 `{detail}` with the failure reason and how many were already delivered |

## Support (`/api/support/`)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `` | user | List the current user's tickets |
| POST | `` | user | Open a new ticket (`subject` + first `message`) |
| GET | `<ticket_id>/` | owner/admin | Ticket detail with full message thread |
| POST | `<ticket_id>/messages/` | owner/admin | Reply on a ticket; admin replies set status to `pending`, user replies set it back to `open` |
| POST | `<ticket_id>/close/` | owner/admin | Close a ticket |
| GET | `admin/` | admin | List all tickets, paginated, optional `?status=` filter |
