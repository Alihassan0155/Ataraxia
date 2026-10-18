# S3 video upload dry-run — no uploads

**Local mapping complete; AWS identity/bucket/permission verification BLOCKED.** No S3 bucket was created, no videos uploaded and no Supabase records updated by this audit.

Proposed destination configuration, read from `backend/reports/s3_dry_run_20261018/destination.env`:

- Bucket: `ataraxia-fyp-videos-068371986822-ap-south-1-an`
- Region: `ap-south-1`
- Prefix: `videos/`

These are the user's proposed destination settings, **not confirmation that the bucket exists, belongs to the account, or is in that region**. Credentials are not hardcoded or stored in this configuration.

## Actual verification results

| Check | Result |
|---|---|
| Live Supabase video IDs | Exactly 1,140; identical to approved snapshot scope |
| FineVideo files matched | 793 |
| TikTok files matched | 347 |
| Source SHA-256 matches stored media hashes | 1,140 / 1,140 |
| Missing/hash-mismatched/zero-byte selected files | 0 |
| Unique destination object keys | 1,140 |
| Total matched bytes | 4,492,269,234 (4.49 GB decimal) |
| Boto3 credential provider chain | No credentials found |
| AWS account identity | Unverified |
| Bucket existence/owner/actual region | Unverified |
| Read/list/upload permissions | Unverified |
| Existing S3 destination objects/collisions | Not checked without credentials |

Both the current user and normal environment were checked. No AWS environment variables or `C:\Users\ALI\.aws\config` / `credentials` files were available; project-local `.aws` files were absent too. The SDK returned `credentials=None`. No attempt was made to infer ownership from the account number embedded in the bucket name.

Boto3 was installed into the isolated audit dependency directory, leaving the running backend/model environments unchanged. The locally configured provider chain was used; secrets were neither requested in chat nor printed. EC2 metadata probing was disabled for this local-PC audit. Signed AWS checks cannot proceed until the existing profile/configuration location is supplied.

With credentials available, the read-only checker calls STS identity, `HeadBucket` with `ExpectedBucketOwner` set to the actual STS account, region verification and prefix listing. It optionally gathers IAM policy-simulation evidence, without a test upload. [AWS documents that HeadBucket errors do not distinguish all missing-bucket and permission failures](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/head_bucket.html). [IAM policy simulation](https://docs.aws.amazon.com/boto3/latest/reference/services/iam/client/simulate_principal_policy.html) is reported separately and does not establish every bucket-policy/SCP/KMS condition or prove a successful PUT.

## Exact source-to-destination manifest

Full manifest (all 1,140 records):

- `backend/reports/s3_dry_run_20261018/audit/manifest.csv`
- `backend/reports/s3_dry_run_20261018/audit/manifest.jsonl`

| Video ID | Exact selected source path | Proposed S3 object key |
|---|---|---|
| FV000002 | `E:\ALI\FineVideo\FineVideo\videos\FV000002.mp4` | `videos/finevideo/FV000002.mp4` |
| TT_6655484375297166597 | `E:\ALI\Ataraxia\data\fyp_videos_1250\videos\videos\6655484375297166597.mp4` | `videos/tiktok/TT_6655484375297166597.mp4` |

Source roots scanned:

- `E:\ALI\FineVideo\FineVideo\videos`
- `E:\ALI\Ataraxia\data\fyp_videos_1250\videos\videos`
- `E:\ALI\fyp_videos_1250\videos\videos`

The 347 TikTok IDs have multiple candidate paths across local roots. Only one source per approved ID was selected, preferring the stored reference and requiring its actual file SHA-256 to equal the stored hash. Other candidate paths are recorded separately; unselected copies were not all independently hashed. No duplicate uploads are proposed. Additional manifest/source videos are excluded from the output.

All selected files were checked for size/mtime stability during hashing. The manifest records source path, key/URI, size, actual and expected hash, mapping status and alternative paths. Every destination is marked `not_verified` until AWS access/listing succeeds. Existing destination keys, if later found, require content verification and overwrite review; an ETag or size alone is not treated as a SHA-256 match.

## Reproduction

`backend/video_data/s3_dry_run.py` has no upload, bucket-create or database-write implementation. The checked-in tests cover exact destination keys, source/prefix rejection, hash-based copy selection, missing files and duplicate IDs. All 84 backend tests pass. Saved manifest/report checksums were reread and verified.

After configuring the existing AWS profile/path locally, run into a NEW output directory:

```powershell
backend/.venv-import/Scripts/python.exe -B -m backend.video_data.s3_dry_run --env-file backend/reports/s3_dry_run_20261018/destination.env --sdk-path backend/reports/s3_dry_run_20261018/dependencies --media-root E:/ALI/FineVideo/FineVideo/videos --media-root E:/ALI/fyp_videos_1250/videos/videos --out backend/reports/s3_dry_run_20261018/audit_verified_NEW
```

For a nondefault setup, use the existing `AWS_PROFILE`, `AWS_CONFIG_FILE` and/or `AWS_SHARED_CREDENTIALS_FILE` settings. Provide only profile names or file locations in chat; never secret values. After successful AWS verification, present the final manifest and request separate explicit approval before any upload or S3-related Supabase update.

This audit does not change or activate an S3 upload component in the separately approved semantic synchronization watcher.
