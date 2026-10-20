
"""Services for onboarding preferences and recommendation candidates."""

from threading import Lock

from .sampling import balanced_sample, valid_media


_interests_cache = None
_interests_lock = Lock()


class PreferenceService:
    def __init__(self, repository, bucket, rng=None):
        self.repository = repository
        self.bucket = bucket
        self.rng = rng

    def interests(self):
        global _interests_cache

        if _interests_cache is None:
            with _interests_lock:
                if _interests_cache is None:
                    _interests_cache = self.repository.interests()

        return {"interests": _interests_cache}

    def get(self, user_id):
        return {"interests": self.repository.preferences(user_id)}

    def replace(self, user_id, ids):
        return {"interests": self.repository.replace(user_id, ids)}

    def candidates(self, user_id, limit=50):
        if not self.bucket:
            raise RuntimeError("S3 bucket configuration missing")

        selected, rows = self.repository.candidate_pool(user_id)
        groups = {row["id"]: [] for row in selected}

        for row in rows:
            if row["category_id"] not in groups:
                continue

            if not valid_media(
                row["media_uri"],
                row["availability"],
                self.bucket,
            ):
                continue

            # A valid URI must refer to this exact stable video identity.
            if row["media_uri"].rsplit("/", 1)[-1] != row["video_id"] + ".mp4":
                continue

            groups[row["category_id"]].append(
                {
                    key: row[key]
                    for key in (
                        "video_id",
                        "title",
                        "language",
                        "duration_seconds",
                        "orientation",
                        "category_id",
                        "category_name",
                    )
                }
            )

        candidates = balanced_sample(groups, limit, self.rng)

        return {
            "videos": candidates,
            "count": len(candidates),
            "limit": limit,
            "strategy": "balanced_random_metadata_v1",
        }
