# Login → preferences latency — 2026-10-20

> Runtime timing recording, Timings buttons and Server-Timing headers were subsequently removed at the user's request. Measurements below are historical; instructions to tap Timings no longer apply. Performance and reliability fixes remain.

Implemented locally. Feed, playback, sampling, schema and production data were
not changed in this task. Earlier feed changes remain in the working tree.
No commit, push or deployed application update was performed.

## Confirmed findings

1. `loadPreferenceSelection` awaited categories and then saved preferences.
   These requests are independent; their times unnecessarily added together.
2. The preference screen returned a full-screen skeleton until both requests
   completed. Even a ready public catalogue remained hidden while private
   preferences loaded.
3. Every login reread the public catalogue. Although the backend already cached
   taxonomy, the mobile app did not prefetch/reuse it across startup and login.
4. Startup's splash held for 1,200 ms and then faded for 500 ms, independently of
   readiness. This affects fresh launches, not an already-visible login screen.
5. SecureStore token writes were sequential. Development Strict Mode could also
   initiate overlapping session restoration requests.

The reported physical-iPhone 8–10 seconds was **not reproduced or attributed to
one measured stage**: no authorized test credentials or physical device trace
were available. Claiming a measured 8–10-second fix would be unsupported. Existing
login code did not redundantly call `/auth/me` after successful password login;
no verification was removed or bypassed.

## Changes

- Load public categories and saved preferences concurrently. Render categories as
  soon as ready, with “Loading your saved interests…” and disabled selection/
  Continue until saved preferences load successfully.
- Prefetch only public taxonomy at startup and while login is displayed. Coalesce
  pending reads and cache successful public data for five minutes. Failed reads
  remain retryable. No private preferences, passwords or authentication results
  are cached by this loader.
- Parallelize the two independent secure-token writes; wait for **both** to settle
  before reporting success or clearing partial writes on failure.
- Coalesce only concurrent session restoration calls. Results are not cached to
  skip future launches. Existing authentication and refresh validation remain.
- Remove the fixed splash hold; retain a 300-ms fade and the actual session
  progress/error overlay. This does not remove the root navigation readiness gate.
- Keep duplicate login submissions blocked. Always route successful fresh login/
  launch to preferences, including returning users. Saved values are preselected;
  only successful explicit Continue saves navigate to feed. Minimum-one-interest,
  Retry and failure handling remain intact. Stale private reads are cancelled.

## Measurements

| Stage | Observed result |
|---|---|
| Physical login → preference readiness | User reports 8–10 s; not independently measured |
| Actual password authentication | Pending authorized credentials; no account/login probe performed |
| Public category HTTP, cold application cache | 296.60 ms; 18 categories; DB/service 276.62 ms |
| Public category HTTP, warm application cache | 1.50 and 1.12 ms |
| Supabase public Auth **health** endpoint | 1,339 ms cold HTTPS connection; 305 and 301 ms reused connection |
| Saved-preference HTTP for real user | Pending authorized credentials |
| SecureStore / router / native layout | Instrumented; pending iPhone execution |
| Controlled category=120 ms, preference=200 ms fixture | Before 327.29 ms; parallel 203.74 ms; prefetched 203.36 ms |
| Programmed splash duration | 1,200-ms hold + 500-ms fade → no hold + 300-ms fade |

Controlled timings are five-run Node medians, not production login improvement.
The public Auth health probe measures connection/service reachability, **not**
password verification or session creation. Cold categories are only a fraction of
the reported delay in this environment; actual Supabase login, private preference
reads and phone/network/rendering remain candidates requiring the stage trace.

The initial probe found no existing listener on port 8000. A temporary local
backend on port 8011 was used for public-category HTTP measurements; it was
stopped after profiling. No production preferences were read or written for a
fabricated identity. Public taxonomy and provider health were the only real API
probes. Raw credentials, tokens and API bodies were not logged or saved.

Evidence: `backend/reports/login_latency_20261020/before.json`,
`public_probes.json`, `controlled_comparison.json`.

## Stage diagnostics

In development, tap **Timings** on the preference screen. The numeric output
separates:

- `login_http_ms`: client/backend/Supabase complete login response;
- `login_supabase_auth_ms`: backend provider password-auth call only;
- `session_storage_ms`: both secure writes;
- `session_restore_ms`, `access_token_read_ms`: fresh-launch restore/storage;
- `router_ready_ms`, `navigation_requested_ms`, `preference_screen_mounted_ms`:
  navigation readiness/request/mount offsets;
- `categories_client_ms` and `categories_cache_hit` (0/1 flag): public catalogue;
- `preferences_client_ms`, `preferences_supabase_auth_ms`,
  `preferences_preferences_db_ms`: private HTTP/auth/database stages;
- `preferences_ready_ms`: both validated datasets ready;
- `preference_screen_layout_ms`, `preferences_frame_callback_ms`: layout/next-JS-
  frame callbacks. These are rendering proxies, **not proof of native pixel paint**.

Offsets are relative to login submission or fresh root startup; individual
durations overlap and must not be added blindly. With prefetched public data,
some provider category timings precede login and will be absent from the new
attempt. `Server-Timing` contains numeric Supabase/DB/request durations only.

## Validation

- TypeScript: passed.
- Mobile tests: 22 passed, including immediate parallel request start, early
  category rendering, pending Continue gate, failed reads, public-cache retry/
  expiry, coalesced restoration, concurrent secure writes and partial-write cleanup.
- Backend suite: 125 passed; seven opt-in isolated-security tests skipped.
- Local mocked HTTP tests confirm authentication still enforced and distinct
  Supabase/preference-DB/request timing headers; login response shape unchanged.
- Lint remains unavailable because ESLint/config are absent; no auto-install or
  bootstrap was performed.
- Physical iPhone rendering/navigation timing and successful real-user login
  remain unverified.

## Files changed in this task

- `mobile/src/app/(auth)/login.tsx`
- `mobile/src/app/(onboarding)/interests.tsx`
- `mobile/src/app/_layout.tsx`
- `mobile/src/components/animated-icon.tsx`
- `mobile/src/services/auth.ts`, `preference-flow.ts`
- New `mobile/src/services/onboarding-data.ts`, `onboarding-timing.ts`
- `backend/main.py` (auth timing headers only), `backend/onboarding/api.py`
  (category/private-read timings only)
- `backend/tests/test_onboarding.py`, mobile preference/refresh test fixtures,
  new `mobile/tests/onboarding-latency.test.cjs` and `profile-onboarding.cjs`

## Verify on iPhone

1. Restart FastAPI to expose new stage timing headers and reload Expo.
2. Confirm the phone can reach the configured hotspot backend.
3. Log in using an authorized account; do not send passwords or tokens in chat.
4. Observe categories appearing while saved interests load. Continue must stay
   disabled until successful loading plus at least one selection.
5. Tap Timings and retain only numeric output. Compare provider time, private DB
   time, navigation request-to-mount and data-ready-to-frame callback gaps.
6. Repeat a warm login and a killed/reopened app launch. Both must require
   explicit Continue; normal same-session navigation must not restart onboarding.
7. Disable networking while private preferences load: remain on interests with
   Retry and disabled Continue, never silently treat failure as empty preferences.

Automated commands (repository root):

```powershell
mobile\node_modules\.bin\tsc.cmd --noEmit -p mobile/tsconfig.json
node --test mobile/tests/*.test.cjs
node mobile/tests/profile-onboarding.cjs
backend\.venv-onboarding\Scripts\python.exe -B -m unittest discover -s backend/tests -p 'test_*.py'
```
