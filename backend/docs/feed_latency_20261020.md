# Feed latency and reliability — 2026-10-20

> Runtime timing recording, Timings buttons and Server-Timing headers were subsequently removed at the user's request. Measurements below are historical; instructions to tap Timings no longer apply. Performance and reliability fixes remain.

Implemented locally; restart FastAPI and reload Expo to use it. No production
schema/data, S3 objects, categories, annotations, embeddings or sampling algorithm
were changed. No commit, push or application deployment was performed.

## Delivery and sampling

The mobile feed uses authenticated `GET /recommendations/feed?page_size=5`.
The server runs the existing balanced random sampler once for up to 50 unique
videos and returns the first five metadata records plus one first-video URL.
The remaining metadata arrives through one background page (page_size=45),
without another sample or database read. Initial pages are capped at ten.
JSON batches avoid relying on native Expo streaming support.

User-bound opaque cursors retain a bounded in-memory snapshot (256 snapshots,
ten-minute TTL). A repeated cursor returns the same page. Expiry, restart or
eviction returns 410; the app offers an explicit refresh instead of mixing a new
random sample into an old one. Existing videos remain usable during page errors;
Retry requests the same cursor. This is intended for the current single-worker
local backend. Multiple workers/replicas require shared snapshot storage or sticky
routing; otherwise cursors can return 410. This change does not deploy Redis.

Only the first URL is returned initially. The current/next videos obtain URLs
near use through `GET /catalogue/videos/{video_id}/playback`. References are read
from the verified database records, not reconstructed from IDs. A user-bound
snapshot may reuse those verified references for at most five minutes, then the
playback route rechecks PostgreSQL. URLs expire in 300 seconds; responses are
no-store. Other sample references and hashes are never returned to the client.

S3 signing now uses the configured regional endpoint. The initial diagnostic
without that endpoint received 307 redirects. With regional signing, real
read-only Range GETs for one FineVideo and one TikTok object both returned 206,
exactly 1,024 bytes. No Range header is frozen into the signature, so native
players may seek using different byte ranges. Objects remain private.

## Database and request changes

The previous candidate lookup did separate preference/category and video reads.
One LEFT JOIN now returns the same eligible rows and retains selected categories
having no videos. The read-only setting and SELECT are pipelined, reducing network
round trips. Output ordering and seeded sampling equivalence were tested.

EXPLAIN ANALYZE on a read-only category fixture using production video/taxonomy
metadata measured about 33.6 ms server execution in the final run. Remote round
trips dominate. No index migration was justified for the 1,140-video catalogue;
capture another plan if the dataset grows before considering a category expression
index. No production index or migration was applied.

The client shares one token refresh across concurrent 401s, reuses an already
refreshed token for late stale requests and bounds complete JSON request/body
download to 20 seconds. Page/media GETs retry transient errors once with backoff;
authentication failures and expired snapshots do not retry indefinitely.
Preference PUTs are not automatically retried. Mandatory selection and save-before-
navigation behavior are preserved.

The feed uses a virtualized paged FlatList with memoized video items. Only the
current and next item load media; older buffers are released. Offscreen/background
playback pauses. Source replacements use asynchronous native loading and are
serialized to prevent stale swipe requests overwriting a newer source. Native
controls provide pause and seeking. URL renewal preserves playback position;
buffering timeout/error recovery is bounded, with manual Retry afterward.

No whole-bucket fallback is used by the mobile feed. Empty preferences/candidates
offer interest selection; server errors remain errors. Existing legacy endpoints
are retained for compatibility.

## Measurements and limits

Final five-run medians from an **in-process HTTP fixture benchmark**, using the
same two taxonomy categories and read-only production metadata queries:

| Metric | Before | After |
|---|---:|---:|
| Candidate DB transaction round trip | 1,770 ms | 1,079 ms |
| First candidates and first signed URL available | 1,783 ms | 1,083 ms |
| All 50 candidate metadata records available | 1,783 ms | 1,085 ms |
| First response bytes | 22,492 | 1,888 |
| Remaining cached metadata page | — | 2.27 ms |
| Production authenticated preference-save HTTP | Not measured | Not measured |
| iPhone first rendered video frame | Not measured | Not measured |

The first-response reduction was about 39% in this run. WAN timings varied across
exploratory runs; these are not universal speed guarantees. Auth-provider time,
phone networking, S3 media download and decoding are excluded. The before response
contains 50 signed URLs; after delivers metadata progressively and signs later
videos near playback. This does not claim all 50 media files are buffered.

S3 signing alone measured about 0.14 ms per URL in the preliminary profile; it
was not the dominant server cost. Real regional Range reads took about 1.02 s
(FineVideo) and 1.81 s (TikTok), including local HTTP connection setup. These are
not first-frame measurements. Local isolated PostgreSQL preference replacement
measured 22.96 ms median; production preference writes were not performed.

Evidence: `backend/reports/feed_latency_20261020/comparison.json`,
`integration.json`, `s3_range_check_regional.json`. The earlier `profile.json`
and nonregional Range check are exploratory records; the final comparison uses
verified explicit read-only transactions and both complete query shapes.

`Server-Timing` exposes numeric preference DB, candidate, media DB/signing and
total request durations. Development-only mobile **Timings** prints numeric
milliseconds since Continue: preference_save_ms, first_candidates_ms,
first_frame_ms and all_candidates_ms. It prints no tokens, identities or URLs.
The first-frame event is instrumented but has not been exercised on an iPhone.

## Validation

- TypeScript: passed.
- Mobile service/flow tests: 16 passed (timeouts, refresh concurrency, cancellation,
  partial pages/retry, duplicates, expiry, initial URL reuse and mandatory interests).
- Backend suite: 125 passed, seven opt-in isolated-security tests skipped.
- Additional isolated PostgreSQL rehearsal: passed. Same candidate rows, seeded
  sampler output, 50 unique videos balanced 25/25, empty-category retention, user
  isolation and invalid-update atomicity. Temporary fixture database removed and
  local PostgreSQL server stopped afterward.
- Real read-only S3 range checks: 2/2 passed.
- Lint prerequisite check: blocked because ESLint/config are absent. No dependency
  installation or configuration bootstrap was performed.

No authorized test-account credentials are configured. Production authenticated
preference submission and end-to-end HTTP identity checks remain pending. Fixture
identities exist only in isolated tests; production authentication was not bypassed.
Physical-device rapid swiping, buffering, visual smoothness and lifecycle recovery
remain unverified; automated tests cover the request/service behavior.

## Files in this change

- Backend: `main.py`, `onboarding/api.py`, `repository.py`, `service.py`, new
  `onboarding/delivery.py`.
- Mobile: `src/app/(tabs)/index.tsx`, `src/app/(onboarding)/interests.tsx` (timings
  and confirmation revision), `src/services/auth.ts`, new `feed.ts`, `request.ts`,
  `performance.ts`, and `src/components/feed-video.tsx`.
- Tests/utilities: `backend/tests/test_feed_delivery.py`, `integration_feed.py`,
  `profile_feed.py`, `mobile/tests/feed.test.cjs`.

Prior navigation and nonempty-preference edits remain intact.

## iPhone verification

Restart the existing backend terminal:

```powershell
cd E:\ALI\Ataraxia
backend\.venv-onboarding\Scripts\python.exe -B -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Keep `mobile/.env` pointing to `http://192.168.137.1:8000`. In a second terminal:

```powershell
cd E:\ALI\Ataraxia\mobile
$env:REACT_NATIVE_PACKAGER_HOSTNAME='192.168.137.1'
npx expo start --clear --lan
```

1. Connect iPhone to the Windows hotspot. Safari `/health` must return healthy.
2. Scan the Expo QR code. Log in with an authorized account; confirm at least one
   interest and press Continue. Observe first video before background loading ends.
3. Tap Timings after the first frame and after the full sample loads. Compare the
   numeric entries; never share token responses or signed URLs.
4. Swipe rapidly forward/back; only the active video should play. Seek and pause.
5. Leave the screen open beyond five minutes, then seek/swipe; URLs should renew.
6. Briefly disconnect networking while later metadata/media loads; already loaded
   candidates should remain and Retry should recover without duplicates.
7. Background and reopen Expo; only the visible video should resume. A fresh app
   launch still requires explicit preference confirmation.
8. After a backend restart or ten-minute snapshot expiry, retry a pending page;
   use Refresh feed on 410. Multi-worker deployment needs shared snapshots first.

Reproduce local automated checks:

```powershell
cd E:\ALI\Ataraxia
mobile\node_modules\.bin\tsc.cmd --noEmit -p mobile/tsconfig.json
node --test mobile/tests/*.test.cjs
backend\.venv-onboarding\Scripts\python.exe -B -m unittest discover -s backend/tests -p 'test_*.py'
```

`python -m backend.tests.profile_feed` performs read-only production metadata
profiling with local fixture HTTP identity and local URL signing; it never writes
preferences or requests S3 objects. `integration_feed` requires the existing
localhost-only PostgreSQL test server on port 55439 and never reads production .env.
