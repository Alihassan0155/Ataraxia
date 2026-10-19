# Preference onboarding backend — prepared 2026-10-19

Implemented and tested; migration 003 has NOT been applied to production. No frontend files, production user data, video records, media objects, model outputs or catalogue views were changed.

## Inspected architecture

The merged backend/main.py now contains Supabase Auth signup/login/refresh/me and prototype S3 playback/feed routes. Mobile src/services/auth.ts uses EXPO_PUBLIC_API_URL, stores access/refresh tokens and sends Authorization: Bearer access_token. The new routes reuse the actual get_current_user dependency, which calls Supabase auth.get_user(token). They never accept a user ID from a request body or trust unverified JWT claims. Existing auth/playback/feed behavior is preserved.

A read-only production inspection found only the eight existing video/taxonomy tables in public; auth.users exists, but no public preference/profile table exists. interest_categories has 19 entries with opaque 64-character IDs: 18 is_onboarding=true entries and one non-onboarding unknown entry. IDs, labels and taxonomy_version are read from PostgreSQL, not hardcoded. Existing canonical source metadata is stored as videos.payload.category, alongside category_original. All 1,140 source metadata labels already map to canonical taxonomy names. Neither Qwen categories nor semantic summaries are used in this initial recommender.

Production inspection confirmed 1,140 videos and 1,140 s3_verified references; semantic and embedding records cover 927 videos. The other 213 remain eligible for metadata-based candidates when their category matches. No production preferences table exists yet.

## API contract

### GET /onboarding/interests

Public discovery endpoint. Stable order: category name, then ID. Returns ONLY selectable existing taxonomy entries. Example subset of the 18-entry response:

```json
{"interests":[
  {"id":"8a52e19efbc500941466763dc45e2d8af3115fb87cc7afb9502f4ac4dc95cb87","name":"Comedy","taxonomy_version":"ataraxia-semantic-taxonomy-v1"},
  {"id":"41fa1620b1e46fcd90cdbc87ac09cf9c0243c83fd4b6fbce220714e0ecc1b849","name":"Gaming","taxonomy_version":"ataraxia-semantic-taxonomy-v1"}
]}
```

Do not hardcode these example IDs in the frontend; fetch and retain returned IDs.

### PUT /users/me/interests

Requires Authorization: Bearer <Supabase access token>. Replaces the authenticated user's complete selection, atomically:

```json
{"category_ids":["8a52e19efbc500941466763dc45e2d8af3115fb87cc7afb9502f4ac4dc95cb87","41fa1620b1e46fcd90cdbc87ac09cf9c0243c83fd4b6fbce220714e0ecc1b849"]}
```

Response has the same interests objects as discovery, restricted to saved choices. Multiple selections are supported. Repeating the same set, including in a different order, performs no preference changes and preserves created_at. Empty category_ids clears the user's selection and returns {"interests":[]}. Duplicate/invalid/unknown/non-onboarding IDs and additional fields such as user_id are rejected. There is a 100-item request safety bound; actual accepted values are determined entirely by taxonomy membership.

### GET /users/me/interests

Same bearer authentication. Returns {"interests":[...]} for the verified user. New users and users with cleared selections receive an empty array. Requests cannot select another user through the URL or body.

### GET /recommendations/cold-start?limit=50

Same bearer authentication. limit is optional, default 50, and must be 1–50. Example structure:

```json
{"videos":[{"video_id":"FV000002","title":"Example source title","language":"en","duration_seconds":12.5,"orientation":"vertical","category_id":"8a52e19efbc500941466763dc45e2d8af3115fb87cc7afb9502f4ac4dc95cb87","category_name":"Comedy"}],"count":1,"limit":50,"strategy":"balanced_random_metadata_v1"}
```

The candidate example illustrates the response schema; it is not a claim about FV000002's actual category/title/duration. No S3 URI, local filesystem path, token, signed URL or full semantic/embedding data is exposed in this response.

## Candidate generation

Within a repeatable-read read-only transaction, load the user's selected category IDs and matching videos by joining existing canonical videos.payload.category to taxonomy.name. Require is_onboarding, exclude unknown, and require availability=s3_verified plus a valid stored media hash. Service validation requires the configured bucket, the exact approved FineVideo/TikTok key structure, and a filename matching video_id; missing/unavailable/conflicting media references are excluded. It does not query S3 on each request: s3_verified is the existing completed-upload audit assertion.

Shuffle each category pool using system randomness, then sample one candidate per nonempty category per round in randomized category order. Redistribute capacity as pools exhaust, stop at limit, and deduplicate video IDs globally. Results may be fewer than 50. Empty preferences or no matching media return count=0, without inventing fallback interests. Sampling is random across calls; unique IDs are guaranteed within each response. No embeddings, semantic ranking, affect ranking, user-state modelling, collaborative filtering or RL are involved.

The exact bucket is read from existing S3_BUCKET_NAME, with AWS_S3_BUCKET as a fallback. No media is downloaded or modified. The prototype playback endpoint still handles its existing test key only; generalizing playback is separate work and was not included.

## Persistence and permissions

Prepared migration: backend/migrations/003_user_interest_preferences.sql. The 2026-10-19 security fix explicitly revokes production default grants from PUBLIC, anon, authenticated and service_role before narrow grants, and asserts the resulting effective table/column permissions. See migration003_security_readiness_20261019.md for the current tested checksum and 121-test readiness report.

One new table: public.user_interest_preferences:

- user_id uuid -> auth.users(id), ON DELETE CASCADE;
- category_id text -> existing interest_categories(id);
- created_at timestamptz default now();
- composite primary key (user_id,category_id).

RLS is enabled. authenticated can SELECT only its own rows via auth.uid(); no direct authenticated INSERT/DELETE/UPDATE is granted. Preference writes pass through the verified FastAPI endpoints and server-only PostgreSQL connection. service_role receives SELECT/INSERT/DELETE plus UPDATE(category_id), required by the existing SELECT FOR UPDATE row lock; anon/PUBLIC receive no privileges. Existing taxonomy permissions are unchanged. The existing server PostgreSQL connection must be kept server-only and have the necessary privileges; do not use an anon client key for persistence.

The repository serializes simultaneous replacements using a transaction-scoped advisory lock keyed by the verified user UUID, including initially empty selections. It validates all category IDs before mutations, applies a set difference and returns saved taxonomy objects. Every query binds user_id; all writes affect only the new preference table. Failure rolls back the entire replacement. User UUID foreign keys prevent nonexistent identities from receiving preferences.

No new profile/account table or authentication provider was invented. No changes to existing user accounts are required. Preferences cannot distinguish never-onboarded from deliberately empty selections; an onboarding-completed flag was not requested or added.

## Errors and deployment blockers

- 401: missing, invalid or expired Supabase bearer token.
- 422: invalid/unknown/duplicate category IDs, forbidden user_id or other extra input, invalid limit.
- 503: database unavailable, missing unapplied preference table, or unavailable candidate configuration. Connection/provider details are not returned.

Production migration approval is the remaining database blocker. Until 003 is applied, taxonomy discovery can operate, while user preference and cold-start routes return sanitized 503 for the missing table. Authentication is already integrated; no insecure bypass is exposed. Frontend should refresh expired tokens using the existing auth service and retry, fetch interests before rendering choices, submit IDs only, and request candidates after preferences save successfully.

Review and explicitly approve migration 003 before deployment. Apply it as a single transaction through the existing Supabase migration process/SQL editor using a trusted owner connection. Do not reapply creation migrations 001/002 or reset tables. No application/SQL deployment was performed here. If rolling back this new feature later, preserve user preferences before removing the new table; disable the new routes first. No rollback SQL that deletes production preference data is run automatically.

## Validation and files

114 backend unit/HTTP tests passed in an isolated dependency environment, including 17 onboarding tests and a test proving main.app uses the existing Supabase verification dependency (provider calls mocked, no production users created). Separate isolated PostgreSQL rehearsal restored the existing eight-table dataset, applied 003 locally and verified persistent multi-select preferences, idempotence, user isolation, invalid/unknown/duplicate rejection, empty selections, concurrent replacement, injected database failure rollback, RLS and denied direct writes. A metadata-only video with no embedding (FV000745) was eligible. Full fingerprints confirmed all original eight tables unchanged after testing.

Integration evidence: backend/reports/onboarding_20261019/integration_results.json. All database rehearsal writes occurred on localhost:55439 in a uniquely named disposable database; production was read-only. The local server is stopped after testing. Existing GPU/model environments were not modified.

Changed/added source:

- backend/main.py: register routes using existing authentication; retain backend-directory launch compatibility.
- backend/requirements.txt: add PostgreSQL driver and the EmailStr validator required by existing auth models.
- backend/onboarding/__init__.py, api.py, repository.py, service.py, sampling.py.
- backend/migrations/003_user_interest_preferences.sql (prepared only).
- backend/tests/test_onboarding.py and integration_onboarding.py.
- backend/docs/preference_onboarding.md (this file).

Run local API after installing requirements into a backend environment:

```powershell
backend/.venv-onboarding/Scripts/python.exe -m uvicorn backend.main:app --reload
```

Existing backend/.env supplies Supabase Auth, PostgreSQL and bucket configuration. Never put database credentials or service credentials in EXPO_PUBLIC_* variables. Open /docs for generated request/response schemas.

Test commands:

```powershell
backend/.venv-onboarding/Scripts/python.exe -B -m unittest discover -s backend/tests -p 'test_*.py'
# Requires the existing localhost-only test server at port 55439:
backend/.venv-onboarding/Scripts/python.exe -B -m backend.tests.integration_onboarding
```

Test environment installation (does not touch frozen GPU environments):

```powershell
backend/.venv-import/Scripts/python.exe -m venv backend/.venv-onboarding
backend/.venv-onboarding/Scripts/python.exe -m pip install -r backend/requirements.txt -r backend/requirements-import.txt httpx
```
